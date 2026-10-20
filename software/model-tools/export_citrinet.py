#!/usr/bin/env python3
"""Export exact archived weights using pinned upstream Jasper arithmetic.

This validates ONNX against upstream encoder/SE components, not the complete
NeMo ASRModel wrapper. Final acceptance still requires validate_nemo.py.
"""
import argparse
import hashlib
import json
import logging
import types
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
import torch.nn as nn
import yaml

ROOT = Path(__file__).resolve().parents[2]


def upstream():
    path = ROOT / 'research/jasper_nemo_v1.23.0.py'
    expected='244e3cd4d19bbbf37aa72d9af9ba5f5f97d23e3d57c828957d647872c1847b8c'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise ValueError('Pinned upstream Jasper source SHA256 mismatch')
    source = path.read_text(encoding='utf-8')
    source = source.replace('from nemo.collections.common.parts.utils import activation_registry',
                            'activation_registry = {"relu": nn.ReLU}')
    source = source.replace('from nemo.core.classes.mixins import AccessMixin',
                            'class AccessMixin:\n    def is_access_enabled(self): return False')
    source = source.replace('from nemo.core.classes.mixins.adapter_mixins import AdapterModuleMixin',
                            'class AdapterModuleMixin:\n    def is_adapter_available(self): return False')
    source = source.replace('from nemo.utils import logging', 'import logging')
    source = source.replace('@torch.jit.script', '')
    module = types.ModuleType('pinned_jasper')
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


class Model(nn.Module):
    def __init__(self, config, state, dynamic=False):
        super().__init__()
        module = upstream()
        blocks, channels = [], config['encoder']['feat_in']
        for i, b in enumerate(config['encoder']['jasper']):
            blocks.append(module.JasperBlock(channels, b['filters'], repeat=b['repeat'],
                kernel_size=b['kernel'], stride=b['stride'], dilation=b['dilation'],
                dropout=b['dropout'], residual=b['residual'], separable=b['separable'],
                activation=nn.ReLU(), conv_mask=True, se=b['se'],
                se_reduction_ratio=b.get('se_reduction_ratio', 8),
                se_context_window=b['se_context_size'], stride_last=b.get('stride_last', False),
                residual_mode=b.get('residual_mode', 'add'), layer_idx=i))
            channels = b['filters']
        self.encoder = nn.Sequential(*blocks)
        self.encoder.load_state_dict({k.removeprefix('encoder.encoder.'): v for k,v in state.items()
                                      if k.startswith('encoder.encoder.')}, strict=True)
        self.decoder = nn.Conv1d(channels, config['decoder']['num_classes'] + 1, 1)
        self.decoder.load_state_dict({k.removeprefix('decoder.decoder_layers.0.'):v for k,v in state.items()
                                      if k.startswith('decoder.decoder_layers.0.')}, strict=True)
        if dynamic:
            # Avoid trace-time sequence-range cache bounds; arithmetic is unchanged.
            for m in self.modules():
                if isinstance(m, module.MaskedConv1d):
                    m.forward = types.MethodType(dynamic_conv, m)
                elif isinstance(m, module.SqueezeExcite):
                    m.forward = types.MethodType(dynamic_se, m)
        self.eval()

    def forward(self, features, lengths):
        encoded, lengths = self.encoder(([features], lengths))
        return self.decoder(encoded[-1]).transpose(1, 2).log_softmax(-1), lengths


def dynamic_conv(self, x, lengths):
    if self.use_mask:
        x = x.masked_fill(torch.arange(x.shape[-1], device=x.device)[None,None,:] >= lengths[:,None,None], 0)
    lengths = self.get_seq_len(lengths)
    return self.conv(x), lengths


def dynamic_se(self, x, lengths):
    valid = torch.arange(x.shape[-1], device=x.device)[None,None,:] < lengths[:,None,None]
    x = x.masked_fill(~valid, 0)
    y = x.sum(-1, keepdim=True) / valid.sum(-1, keepdim=True).to(x.dtype)
    y = self.fc(y.transpose(1,2)).transpose(1,2).sigmoid()
    return x * y, lengths


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--checkpoint-dir', type=Path, default=ROOT/'research/checkpoints/citrinet-256-ls')
    p.add_argument('--output-dir', type=Path, default=ROOT/'research/export/citrinet-256-ls')
    args = p.parse_args()
    torch.set_num_threads(4)
    state = torch.load(args.checkpoint_dir/'model_weights.ckpt', map_location='cpu', weights_only=True)
    config = yaml.safe_load((args.checkpoint_dir/'model_config.yaml').read_text())
    reference, model = Model(config,state), Model(config,state,True)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    output = args.output_dir/'model.onnx'
    rng = np.random.default_rng(173)
    x = torch.from_numpy(rng.normal(size=(1,80,1008)).astype('float32'))
    lengths = torch.tensor([1001])
    with torch.no_grad():
        torch.onnx.export(model,(x,lengths),output,opset_version=17,dynamo=False,
            input_names=['features','feature_lengths'], output_names=['log_probs','encoded_lengths'],
            dynamic_axes={'features':{0:'batch',2:'frames'},'feature_lengths':{0:'batch'},
                          'log_probs':{0:'batch',1:'encoded_frames'},'encoded_lengths':{0:'batch'}})
    session = ort.InferenceSession(str(output),providers=['CPUExecutionProvider'])
    comparisons=[]
    for batch, frames, valid in [(1,1008,[1001]),(1,257,[251]),(2,1120,[1103,957]),(1,64,[63])]:
        x = torch.from_numpy(rng.normal(size=(batch,80,frames)).astype('float32'))
        lengths = torch.tensor(valid)
        with torch.no_grad():
            a,l = reference(x.clone(),lengths)
            b,bl = model(x.clone(),lengths)
        c,cl = session.run(None,{'features':x.numpy(),'feature_lengths':lengths.numpy()})
        np.testing.assert_allclose(a.numpy(),b.numpy(),atol=1e-5,rtol=1e-5)
        np.testing.assert_allclose(a.numpy(),c,atol=5e-4,rtol=5e-4)
        np.testing.assert_array_equal(l.numpy(),cl)
        comparisons.append({'batch':batch,'frames':frames,'valid_lengths':valid,
            'encoded_lengths':cl.tolist(),'max_absolute_error':float(np.max(np.abs(a.numpy()-c))),
            'argmax_equal':bool(np.array_equal(a.numpy().argmax(-1),c.argmax(-1)))})
    np.savez(args.output_dir/'frontend.npz',window=state['preprocessor.featurizer.window'].numpy(),
             fb=state['preprocessor.featurizer.fb'].numpy())
    (args.output_dir/'vocab.txt').write_text('\n'.join(config['decoder']['vocabulary'])+'\n',encoding='utf-8')
    report={'original_nemo_wrapper_validated':False,'reference':'NeMo v1.23.0 JasperBlock + archived weights',
            'torch':torch.__version__,'onnx':onnx.__version__,'onnxruntime':ort.__version__,
            'tests':comparisons,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
    (args.output_dir/'export_validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
