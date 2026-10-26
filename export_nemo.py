#!/usr/bin/env python3
"""Run on an x86 PC (not the KV260): export QuartzNet and Citrinet to ONNX.

    pip install "nemo_toolkit[asr]"
    python export_nemo.py

Then copy the nemo/ folder to the KV260.
"""
import json
import gc
import urllib.request
from pathlib import Path

import nemo.collections.asr as nemo_asr
import torch
torch.set_num_threads(4)
from nemo.utils import logging
logging.set_verbosity(logging.ERROR)

OUT = Path(__file__).resolve().parent / "nemo"
MODELS = {
    "quartznet15x5": "QuartzNet15x5Base-En",
    "citrinet256-ls": "nvidia/stt_en_citrinet_256_ls",
    "citrinet512-ls": "nvidia/stt_en_citrinet_512_ls",
    "citrinet1024-gamma-0.25": "nvidia/stt_en_citrinet_1024_gamma_0_25",
}

OUT.mkdir(exist_ok=True)
for name, pretrained in MODELS.items():
    if (OUT / f'{name}.validation.json').exists():
        print(f'{name}: already exported and validated', flush=True)
        continue
    print(f'Loading {name}: {pretrained}', flush=True)
    checkpoint = OUT / f'{name}.nemo'
    if not checkpoint.exists():
        if name == 'quartznet15x5':
            url = 'https://api.ngc.nvidia.com/v2/models/nvidia/nemo/stt_en_quartznet15x5/versions/1.0.0rc1/files/stt_en_quartznet15x5.nemo'
        else:
            url = f'https://huggingface.co/{pretrained}/resolve/main/{pretrained.split("/")[-1]}.nemo'
        urllib.request.urlretrieve(url, checkpoint)
    cls = nemo_asr.models.EncDecCTCModel if name == 'quartznet15x5' else nemo_asr.models.EncDecCTCModelBPE
    model = cls.restore_from(str(checkpoint), map_location='cpu').eval()
    if not (OUT / f'{name}.onnx').exists():
        # Retain a long mask cache while tracing a short dynamic example.
        # Otherwise the traced SqueezeExcite mask can be frozen at 512 frames.
        model.encoder.update_max_sequence_length(seq_length=8192, device=torch.device('cpu'))
        model.export(str(OUT / f"{name}.onnx"), input_example=model.encoder.input_example(max_dim=256), check_trace=False)

    if hasattr(model, "tokenizer"):
        vocab = [model.tokenizer.ids_to_tokens([i])[0] for i in range(model.tokenizer.vocab_size)]
    else:
        vocab = list(model.decoder.vocabulary)

    pre = model.cfg.preprocessor
    cfg = {
        "features": pre.features,
        "window_size": pre.window_size,
        "window_stride": pre.window_stride,
        "n_fft": pre.get("n_fft"),
        "normalize": pre.normalize,
        "pad_to": pre.get('pad_to', 16),
        "vocab": vocab,
    }
    (OUT / f"{name}.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    import numpy as np
    import torch
    from models import NemoCtcOnnx, _slaney_mel_filters
    # Verify our lightweight features against the loaded NeMo preprocessor.
    adapter = NemoCtcOnnx(name, 4)
    audio = np.random.default_rng(0).normal(0, 0.03, 160123).astype(np.float32)
    with torch.no_grad():
        expected, expected_len = model.preprocessor(input_signal=torch.from_numpy(audio[None]), length=torch.tensor([len(audio)]))
    actual = adapter._features(audio)
    error = float(np.max(np.abs(actual - expected.numpy())))
    print(f'{name} feature max abs error: {error:.6g}', flush=True)
    assert error < 0.002, f'Feature mismatch: {error}'
    import soundfile as sf
    paths = list((OUT.parent / 'data').glob('*.wav'))
    paths.sort(key=lambda path: sf.info(path).duration)
    checks = []
    for path in [paths[0], paths[-1]]:
        speech, _ = sf.read(path, dtype='float32')
        hyp = adapter.transcribe(speech)
        print(f'{name} dynamic graph check {path.stem} ({len(speech)/16000:.3f}s): {hyp}', flush=True)
        checks.append({'clip': path.stem, 'audio_s': len(speech)/16000, 'hyp': hyp})
    (OUT / f'{name}.validation.json').write_text(json.dumps({'max_abs_feature_error': error, 'shape': list(actual.shape), 'valid_frames': int(expected_len[0]), 'dynamic_graph_checks': checks}, indent=2))
    del adapter
    print(f"{name}: {len(vocab)} tokens, {pre.features} mels, normalize={pre.normalize}", flush=True)
    del model
    gc.collect()
