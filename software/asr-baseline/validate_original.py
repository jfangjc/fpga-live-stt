#!/usr/bin/env python3
"""Host-only comparison using the original NVIDIA JasperBlock implementation.

Dependencies: torch (CPU), onnx, PyYAML plus the baseline requirements.
Only the unused Swish import is replaced by torch.nn.SiLU; this checkpoint uses
ReLU. Checkpoint tensors are loaded with weights_only=True.
"""
import json
import types
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
import torch.nn.functional as F
import yaml

from quartznet_cpu import decode, frontend, read_pcm24, slaney_mel_filters

BASE = Path(__file__).parent


def reference_encoder(state, config):
    source = (BASE / 'reference/jasper_reference.py').read_text()
    source = source.replace('from nemo.collections.asr.parts.activations import Swish', 'Swish = nn.SiLU')
    module = types.ModuleType('quartznet_jasper_reference')
    exec(compile(source, 'jasper_reference.py', 'exec'), module.__dict__)
    channels = config['encoder']['feat_in']
    blocks = []
    for cfg in config['encoder']['jasper']:
        blocks.append(module.JasperBlock(channels, cfg['filters'], repeat=cfg['repeat'],
            kernel_size=cfg['kernel'], stride=cfg['stride'], dilation=cfg['dilation'],
            dropout=cfg['dropout'], residual=cfg['residual'],
            separable=cfg.get('separable', False), activation=torch.nn.ReLU(), conv_mask=True))
        channels = cfg['filters']
    encoder = torch.nn.Sequential(*blocks).eval()
    encoder.load_state_dict({k.removeprefix('encoder.encoder.'): v for k, v in state.items()
                             if k.startswith('encoder.encoder.')}, strict=True)
    return encoder


def torch_frontend(audio, state):
    x = torch.from_numpy(audio[None]).clone()
    x = torch.cat((x[:, :1], x[:, 1:] - 0.97 * x[:, :-1]), dim=1)
    spectrum = torch.stft(x, 512, hop_length=160, win_length=320,
                          window=state['preprocessor.featurizer.window'],
                          center=True, pad_mode='reflect', return_complex=True).abs() ** 2
    features = torch.log(state['preprocessor.featurizer.fb'] @ spectrum + 2 ** -24)
    valid = (len(audio) + 159) // 160
    mean = features[:, :, :valid].mean(dim=2, keepdim=True)
    std = features[:, :, :valid].std(dim=2, keepdim=True)
    features = (features - mean) / (std + 1e-5)
    features[:, :, valid:] = 0
    return features, valid


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('wav', type=Path)
    args = parser.parse_args()
    torch.set_num_threads(4)
    state = torch.load(BASE / 'reference/model_weights.ckpt', map_location='cpu', weights_only=True)
    config = yaml.safe_load((BASE / 'reference/model_config.yaml').read_text())
    encoder = reference_encoder(state, config)
    audio = read_pcm24(args.wav)
    features, valid = frontend(audio)
    expected_features, _ = torch_frontend(audio, state)
    feature_error = float(np.max(np.abs(features[:, :, :valid] - expected_features.numpy()[:, :, :valid])))
    graph = onnx.load(BASE / 'model/model.onnx')
    initializers = {t.name: onnx.numpy_helper.to_array(t) for t in graph.graph.initializer}
    raw_keys = [k for k in initializers if k in state]
    if not all(np.array_equal(initializers[k], state[k].numpy()) for k in raw_keys):
        raise RuntimeError('Unfolded ONNX tensors differ from original checkpoint')
    stats = []
    hooks = []
    for name, layer in encoder.named_modules():
        if isinstance(layer, torch.nn.Conv1d):
            def record(layer, inputs, output, name=name):
                macs = output.numel() * layer.in_channels // layer.groups * layer.kernel_size[0]
                kind = 'depthwise' if layer.groups == layer.in_channels and layer.groups > 1 else 'pointwise'
                stats.append({'name': name, 'kind': kind, 'macs': macs,
                              'weight_shape': list(layer.weight.shape), 'output_shape': list(output.shape)})
            hooks.append(layer.register_forward_hook(record))
    with torch.inference_mode():
        encoded, lens = encoder(([expected_features], torch.tensor([valid])))
        logits = F.conv1d(encoded[-1], state['decoder.decoder_layers.0.weight'],
                          state['decoder.decoder_layers.0.bias']).transpose(1, 2)
        expected = F.log_softmax(logits, dim=-1).numpy()
    for hook in hooks:
        hook.remove()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(BASE / 'model/model.onnx'), options,
                                   providers=['CPUExecutionProvider'])
    current = session.run(None, {'audio_signal': features})[0]
    trimmed = session.run(None, {'audio_signal': features[:, :, :valid].copy()})[0]
    n = int(lens[0])
    vocab = {int(line.rsplit(' ', 1)[1]): line.rsplit(' ', 1)[0]
             for line in (BASE / 'model/vocab.txt').read_text(encoding='utf-8').splitlines()}
    raw = expected[:, :n]
    np.testing.assert_allclose(trimmed[:, :n], raw, rtol=1e-4, atol=1e-3)
    boundary_checks = []
    for samples in (16000, 16001, 32000):
        subset = audio[:samples]
        candidate, length = frontend(subset)
        truth_features, _ = torch_frontend(subset, state)
        with torch.inference_mode():
            truth_encoded, truth_lens = encoder(([truth_features], torch.tensor([length])))
            truth_logits = F.conv1d(truth_encoded[-1], state['decoder.decoder_layers.0.weight'],
                                    state['decoder.decoder_layers.0.bias']).transpose(1, 2)
            truth = F.log_softmax(truth_logits, dim=-1).numpy()[:, :int(truth_lens[0])]
        actual = session.run(None, {'audio_signal': candidate[:, :, :length].copy()})[0]
        np.testing.assert_allclose(actual, truth, rtol=1e-4, atol=1e-3)
        boundary_checks.append({'samples': samples, 'max_abs_error': float(np.max(abs(actual - truth))),
                                'argmax_agreement': float(np.mean(actual.argmax(-1) == truth.argmax(-1)))})
    result = {
        'mel_filter_max_abs_error': float(np.max(abs(slaney_mel_filters() - state['preprocessor.featurizer.fb'][0].numpy()))),
        'frontend_max_abs_error': feature_error,
        'unfolded_tensors_exact': len(raw_keys),
        'valid_encoder_frames': n,
        'legacy_logprobs_max_abs_error': float(np.max(abs(current[:, :n] - raw))),
        'trimmed_logprobs_max_abs_error': float(np.max(abs(trimmed[:, :n] - raw))),
        'legacy_argmax_agreement': float(np.mean(current[:, :n].argmax(-1) == raw.argmax(-1))),
        'trimmed_argmax_agreement': float(np.mean(trimmed[:, :n].argmax(-1) == raw.argmax(-1))),
        'original_transcript': decode(raw, vocab, n),
        'trimmed_transcript': decode(trimmed, vocab, n),
        'encoder_macs': sum(s['macs'] for s in stats),
        'depthwise_macs': sum(s['macs'] for s in stats if s['kind'] == 'depthwise'),
        'pointwise_macs': sum(s['macs'] for s in stats if s['kind'] == 'pointwise'),
        'layers': stats,
        'boundary_checks': boundary_checks,
    }
    report = BASE.parents[1] / 'reports/quartznet_original_parity.json'
    report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'layers'}, indent=2))


if __name__ == '__main__':
    main()
