"""Fetch weights without inference. Run before the timed sequential suite."""
import json
from pathlib import Path
from faster_whisper.utils import download_model
from moonshine_onnx.model import _get_onnx_weights
from moonshine_voice import get_model_for_language, ModelArch

weights = {}
for size in ['base', 'small', 'large-v3-turbo']:
    print('Downloading Whisper', size, flush=True)
    weights['whisper-' + size] = download_model(size)
print('Downloading Moonshine Tiny float32', flush=True)
weights['moonshine-tiny'] = list(_get_onnx_weights('tiny', 'float'))
for size in ['tiny', 'small']:
    print('Downloading Moonshine Streaming', size, flush=True)
    path, arch = get_model_for_language('en', getattr(ModelArch, size.upper() + '_STREAMING'))
    weights['moonshine-streaming-' + size] = str(path)
Path(__file__).with_name('weights.json').write_text(json.dumps(weights, indent=2))
print('All weights cached', flush=True)
