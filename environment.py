"""Record board and benchmark metadata without loading inference models."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import wave

here = Path(__file__).resolve().parent
durations = []
for path in (here / 'data').glob('*.wav'):
    with wave.open(str(path)) as wav:
        durations.append(wav.getnframes() / wav.getframerate())
packages = ['numpy', 'soundfile', 'jiwer', 'onnxruntime', 'faster-whisper', 'ctranslate2', 'moonshine-voice', 'useful-moonshine-onnx']
metadata = {
    'board_ip': '192.168.1.111',
    'device_tree_model': Path('/proc/device-tree/model').read_text().strip('\0'),
    'platform': platform.platform(),
    'python': platform.python_version(),
    'os_release': Path('/etc/os-release').read_text(),
    'lscpu': subprocess.check_output(['lscpu'], text=True),
    'meminfo': Path('/proc/meminfo').read_text(),
    'packages': {p: importlib.metadata.version(p) for p in packages},
    'cpu_governor_available': Path('/sys/devices/system/cpu/cpufreq/policy0/scaling_governor').exists(),
    'thermal_zone_files': [str(p) for p in Path('/sys/class/thermal').glob('thermal_zone*/temp')],
    'clips': len(durations),
    'total_audio_s': sum(durations),
    'audio_min_s': min(durations),
    'audio_max_s': max(durations),
    'manifest_sha256': hashlib.sha256((here / 'data/manifest.tsv').read_bytes()).hexdigest(),
    'threads': 4,
    'warmup_clips': 2,
    'cooldown_s': 30,
    'streaming_measurement': 'Full clip available -> final transcript via offline API; no simulated real-time pacing',
    'moonshine_streaming_threads': 'Vendor ONNX Runtime automatic thread configuration on four available cores',
}
(here / 'environment.json').write_text(json.dumps(metadata, indent=2))
print(json.dumps(metadata, indent=2))
