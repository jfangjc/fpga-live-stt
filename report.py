"""Build the final report from completed board measurements only."""
import csv
import hashlib
import html
import json
import math
import re
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'results'
NAMES = {
    'quartznet15x5': 'QuartzNet15x5',
    'citrinet256-ls': 'Citrinet-256-LS',
    'citrinet512-ls': 'Citrinet-512-LS',
    'citrinet1024-gamma-0.25': 'Citrinet-1024-gamma-0.25',
    'whisper-base': 'Whisper Base',
    'whisper-small': 'Whisper Small',
    'whisper-large-v3-turbo': 'Whisper Large-V3-Turbo',
    'moonshine-tiny': 'Moonshine Tiny',
    'moonshine-streaming-tiny': 'Moonshine Streaming Tiny',
    'moonshine-streaming-small': 'Moonshine Streaming Small',
}
env = json.loads((HERE / 'environment.json').read_text())
status = json.loads((OUT / 'status.json').read_text())
by_name = {row['model']: row for row in status}
summaries = {name: json.loads((OUT / f'{name}.json').read_text()) for name in NAMES if (OUT / f'{name}.json').exists() and by_name.get(name, {}).get('returncode') == 0}

# Independently recompute the aggregates from all per-clip records.
for name, summary in summaries.items():
    rows = list(csv.DictReader((OUT / f'{name}.csv').open(encoding='utf-8')))
    assert len(rows) == 40 == summary['clips']
    actual_ids = [row['clip'] for row in rows]
    expected_ids = [line.split('\t')[0] for line in (HERE / 'data/manifest.tsv').read_text().splitlines()]
    assert actual_ids == expected_ids
    times = sorted(float(row['proc_s']) for row in rows)
    def percentile(q):
        x = (len(times) - 1) * q
        lo = int(x)
        return times[lo] + (times[min(lo + 1, len(times)-1)] - times[lo]) * (x - lo)
    assert abs(round(percentile(.5), 3) - summary['latency_p50_s']) < .0011
    assert abs(round(percentile(.9), 3) - summary['latency_p90_s']) < .0011
    rtf = sum(float(row['proc_s']) for row in rows) / sum(float(row['audio_s']) for row in rows)
    assert abs(rtf - summary['rtf']) < .00051
    assert abs(max(times) - summary['latency_max_s']) < .00051
    edits, reference_words = 0, 0
    for row in rows:
        ref = re.sub(r"[^a-z' ]", ' ', row['ref'].lower()).split()
        hyp = re.sub(r"[^a-z' ]", ' ', row['hyp'].lower()).split()
        previous = list(range(len(hyp) + 1))
        for i, word in enumerate(ref, 1):
            current = [i]
            for j, other in enumerate(hyp, 1):
                current.append(min(current[-1] + 1, previous[j] + 1, previous[j-1] + (word != other)))
            previous = current
        edits += previous[-1]
        reference_words += len(ref)
    assert abs(edits / reference_words - summary['wer']) < .000051

lines = [
    '# KV260 speech-to-text latency measurements',
    '',
    'Board: `ubuntu@192.168.1.111`, ZynqMP KV260 revB, four Cortex-A53 cores, 3.8 GiB RAM, no swap. Ubuntu 24.04.5 LTS, kernel 6.8.0-1036-xilinx. Measurements were collected on 27 October 2026.',
    '',
    f'The models ran one at a time, in the requested order, using the supplied `bench.py` method. Each model used a separate process, two untimed warmup clips, and the same 40 LibriSpeech test-clean clips (307.170 seconds total, 2.145–18.545 seconds per clip, seed 0). There was a cooldown of at least 30 seconds between models. No inference models ran concurrently. Download and file transfer activity finished before the relevant timed stage.',
    '',
    '**Latency means time from the complete clip being available in memory to the final transcript.** It includes preprocessing and decoding. It excludes model loading, audio file I/O, warmups and downloads. These are CPU measurements; the FPGA/DPU was not used.',
    '',
    '| Model | Clips | p50 (s) | p90 (s) | Max (s) | RTF | WER | Peak RSS (MiB) | Load (s) |',
    '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
]
for name, label in NAMES.items():
    if name in summaries:
        s = summaries[name]
        lines.append(f"| {label} | {s['clips']} | {s['latency_p50_s']:.3f} | {s['latency_p90_s']:.3f} | {s['latency_max_s']:.3f} | {s['rtf']:.3f} | {s['wer']:.2%} | {s['peak_rss_mb']} | {s['load_s']:.2f} |")
    else:
        state = 'Failed' if name in by_name else 'Pending'
        lines.append(f'| {label} | {state} | — | — | — | — | — | — | — |')
lines += [
    '',
    'RTF is total processing time divided by total audio duration; below 1 is faster than real time. Percentiles describe this fixed set of variable-length clips. WER is a sanity check on this small sample, not a full-dataset accuracy estimate. Peak RSS includes model initialization and warmups.',
    'The LS WordPiece decoder retains punctuation spacing, matching the installed NeMo tokenizer’s `clean_up_tokenization_spaces=False` setting. The supplied WER normalizer counts spaced apostrophes in contractions as errors; the saved transcripts expose these formatting differences.',
    '',
    '## Runtime settings',
    '',
    '- NVIDIA models: ONNX Runtime CPU, float32, greedy CTC, NumPy feature extraction, four intra-op threads.',
    '- Whisper: multilingual Base, multilingual Small, and Large-V3-Turbo via faster-whisper/CTranslate2, CPU int8, four threads, language English, beam size 1, no timestamps, VAD off, previous-text conditioning off.',
    '- Moonshine Tiny: original ONNX Runtime adapter and float32 weights (the original constructor defaults to float32), greedy decoding, four intra-op threads and one inter-op thread.',
    '- Moonshine Streaming Tiny/Small: vendor `moonshine-voice` quantized ORT models, `Transcriber.transcribe_without_streaming()` with default vendor decoding/VAD settings. Native ONNX Runtime chooses its thread pools automatically on the four-core board. These rows measure offline full-clip-to-final processing, not streaming first-token latency or live endpointing delay.',
    '',
    'The board kernel did not expose `/sys/devices/system/cpu/cpufreq/policy0/scaling_governor` or any thermal-zone temperature files. The documented performance-governor command could not be applied, and temperature/throttling could not be checked. Temperature fields are therefore unavailable (`NaN` in the raw outputs).',
    '',
    '## Changes required to run the supplied method',
    '',
    '- Added the requested checkpoints, including the exact `-LS` Citrinet variants and Whisper Large-V3-Turbo.',
    '- Downloaded the official QuartzNet checkpoint directly because the installed NeMo registry no longer listed its legacy identifier.',
    '- Matched NeMo feature normalization to valid frames, masked/padded the feature tail, and checked it numerically against each checkpoint’s own preprocessor.',
    '- Supported QuartzNet exports with no length input and cropped padded CTC output frames.',
    '- Decoded the LS checkpoints as WordPiece; retained SentencePiece decoding for the gamma checkpoint and character decoding for QuartzNet.',
    '- Set Moonshine Tiny’s ONNX thread counts explicitly; added the vendor adapter for the streaming checkpoints.',
    '- Added progress records in RAM, durable output copies after each model, and sequential status logs. Final metrics still use the supplied per-clip timing and aggregation calculations.',
    '',
    '## Export validation',
    '',
    '| Model | Maximum absolute feature error vs NeMo |',
    '|---|---:|',
]
for name in list(NAMES)[:4]:
    p = HERE / 'nemo' / f'{name}.validation.json'
    if p.exists():
        lines.append(f"| {NAMES[name]} | {json.loads(p.read_text())['max_abs_feature_error']:.8f} |")
lines += ['', 'Validation used a deterministic 160,123-sample float32 waveform; all errors were below 0.0001. The exported graphs were also exercised with the variable-length speech clips. QuartzNet’s measured WER can be checked against the original README’s 4–6% sanity range.', '', '## Reproducibility', '', f"Manifest SHA-256: `{env['manifest_sha256']}`.", '', 'The `data/` directory contains the exact WAVs and manifest. `results/` contains per-clip transcripts/timings, per-model summaries, logs, `status.json`, and `summary.csv`. `environment.json` records board and package details; `weights.json` records the cached weight paths and Hugging Face revision hashes. `model-files.json` records checksums of the NVIDIA exports and tokenizer configurations.', '', 'The first three models were measured in one sequential stage. After that stage ended, the final export was transferred. The first Citrinet-1024 warmup attempt failed because its short export example froze a mask cache at 512 frames. No latency was recorded from that attempt; its log is preserved in `results/attempts/`. The export was corrected by explicitly initializing a long mask cache and checked on the shortest and longest test clips. The remaining seven models then ran sequentially with another initial cooldown. There were no transfers during timed inference.', '', 'Installed runtime versions:']
for key, value in env['packages'].items():
    lines.append(f'- `{key}=={value}`')
lines += ['', 'Checkpoint sources:', '', '- [NVIDIA QuartzNet](https://api.ngc.nvidia.com/v2/models/nvidia/nemo/stt_en_quartznet15x5/versions/1.0.0rc1/files/stt_en_quartznet15x5.nemo)', '- [NVIDIA Citrinet-256-LS](https://huggingface.co/nvidia/stt_en_citrinet_256_ls)', '- [NVIDIA Citrinet-512-LS](https://huggingface.co/nvidia/stt_en_citrinet_512_ls)', '- [NVIDIA Citrinet-1024 gamma 0.25](https://huggingface.co/nvidia/stt_en_citrinet_1024_gamma_0_25)', '- [Systran faster-whisper models](https://github.com/SYSTRAN/faster-whisper)', '- [Moonshine](https://github.com/moonshine-ai/moonshine)', '']
(HERE / 'BENCHMARK_REPORT.md').write_text('\n'.join(lines), encoding='utf-8')

checksums = {}
for p in sorted((HERE / 'nemo').iterdir()):
    if p.suffix in {'.onnx', '.json', '.nemo'}:
        digest = hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda: f.read(1024*1024), b''):
                digest.update(block)
        checksums[p.name] = {'bytes': p.stat().st_size, 'sha256': digest.hexdigest()}
(HERE / 'model-files.json').write_text(json.dumps(checksums, indent=2))

# A directly labeled log-scale comparison; only measured values enter it.
values = [s[k] for s in summaries.values() for k in ['latency_p50_s', 'latency_p90_s']]
low = 10 ** math.floor(math.log10(min(values)))
high = 10 ** math.ceil(math.log10(max(values)))
position = lambda x: 100 * (math.log10(x)-math.log10(low)) / (math.log10(high)-math.log10(low))
marks = []
for name, label in NAMES.items():
    if name not in summaries:
        marks.append(f'<div class="entry"><div class="labels"><span>{html.escape(label)}</span><span>Failed</span></div></div>')
        continue
    s = summaries[name]
    a, b = position(s['latency_p50_s']), position(s['latency_p90_s'])
    marks.append(f'<div class="entry"><div class="labels"><span>{html.escape(label)}</span><span>{s["latency_p50_s"]:.3f} / {s["latency_p90_s"]:.3f} s</span></div><div class="track" aria-label="{html.escape(label)}: median {s["latency_p50_s"]} seconds, p90 {s["latency_p90_s"]} seconds"><span class="range" style="left:{a:.4f}%;width:{b-a:.4f}%"></span><span class="median" style="left:{a:.4f}%"></span><span class="p90" style="left:{b:.4f}%"></span></div></div>')
ticks = []
power = int(math.log10(low))
while 10 ** power <= high * 1.001:
    value = 10 ** power
    ticks.append(f'<span style="left:{position(value):.4f}%">{value:g}s</span>')
    power += 1
template = (HERE / 'latency-template.html').read_text(encoding='utf-8')
template = template.replace('<!--ROWS-->', '\n'.join(marks)).replace('<!--TICKS-->', '\n'.join(ticks))
(HERE / 'kv260-latency.html').write_text(template, encoding='utf-8')
if len(summaries) == len(NAMES):
    with zipfile.ZipFile(HERE / 'kv260-results.zip', 'w', zipfile.ZIP_DEFLATED) as bundle:
        for p in OUT.rglob('*'):
            if p.is_file():
                bundle.write(p, p.relative_to(HERE))
        for name in ['BENCHMARK_REPORT.md', 'environment.json', 'weights.json', 'model-files.json', 'README.md', 'README-original.md', 'RUNNING.md', 'bench.py', 'models.py', 'run_suite.py', 'export_nemo.py', 'prepare_data.py', 'prefetch.py', 'environment.py', 'report.py', 'latency-template.html', 'requirements.txt', 'requirements-export-freeze.txt']:
            bundle.write(HERE / name, name)
        for p in (HERE / 'nemo').glob('*.json'):
            bundle.write(p, p.relative_to(HERE))
        bundle.write(HERE / 'data/manifest.tsv', 'data/manifest.tsv')
print(f'Validated {len(summaries)} complete 40-clip results; report and chart written.')
