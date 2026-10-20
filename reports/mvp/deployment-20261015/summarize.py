"""Generate CSV and a readable report from downloaded board evidence."""
import csv
import json
from pathlib import Path

folder=Path(__file__).resolve().parent
evidence=folder/'board-reports'
summary=json.loads((evidence/'comparison/summary.json').read_text())
smoke=json.loads((evidence/'local/public-smoke.json').read_text())
fields=['audio_seconds','runs','cpu_p50_ms','cpu_p95_ms','fpga_p50_ms','fpga_p95_ms','speedup_p50','latency_reduction_percent','fpga_rtf_p50','all_logits_bit_exact']
with (folder/'comparison.csv').open('w',newline='') as f:
    writer=csv.DictWriter(f,fields)
    writer.writeheader()
    for r in summary['results']:
        c,p=r['metrics']['cpu'],r['metrics']['fpga']
        writer.writerow(dict(zip(fields,[r['audio_seconds'],r['runs'],c['p50_ms'],c['p95_ms'],p['p50_ms'],p['p95_ms'],r['speedup_p50'],r['latency_reduction_percent'],p['rtf_p50'],r['all_logits_bit_exact']])))
with (folder/'paired-runs.csv').open('w',newline='') as f:
    writer=csv.writer(f)
    writer.writerow(['audio_seconds','index','order','cpu_ms','fpga_ms','cpu_frontend_ms','fpga_frontend_ms','cpu_model_ms','fpga_model_ms','cpu_decode_ms','fpga_decode_ms','fpga_ioctls','fpga_physical_calls','oracle_calls','logits_bit_exact'])
    for r in summary['results']:
        data=json.loads((evidence/('comparison/paired-'+format(r['audio_seconds'],'g')+'s.json')).read_text())
        for row in data['rows']:
            c,p=row['cpu'],row['fpga']
            writer.writerow([r['audio_seconds'],row['index'],row['order'],c['seconds']*1000,p['seconds']*1000,c['frontend_seconds']*1000,p['frontend_seconds']*1000,c['model_seconds']*1000,p['model_seconds']*1000,c['decode_seconds']*1000,p['decode_seconds']*1000,p['counters']['ioctls'],p['counters']['physical_calls'],p['counters']['oracle_calls'],row['logits_bit_exact']])
lines=['# KV260 MVP deployment and measurements — 15 October 2026','',
'Installed on `ubuntu@192.168.1.111` in `/home/ubuntu/kv260-asr-mvp-20261015` from the local `kv260-asr-github` sources and the pinned dependency archive. Existing project directories were preserved. The supplied prebuilt FPGA and native binaries were used; this run did not rebuild RTL.','',
'## Verification','',
'- Fresh Python virtual environment with all eight pinned packages installed.',
'- 60 external dependency files installed and SHA256 verified; full source/asset integrity passed.',
'- All 19 project unit tests passed; distribution check passed.',
'- Public `scripts/run_board.py` entry point: three warm full-logit comparisons passed.',
'- Overlength WAV rejected with a nonzero exit; the public runner restored the bulk board state after that failure.',
'- Sustained test: 300 measured paired calls per duration; every full output tensor, transcript and output length matched the CPU.',
'- Every measured FPGA call recorded 24 ioctls, 128 physical calls, and zero oracle calls; counters were checked by the project runtime.',
'- Bulk firmware, compatible kernel driver, approximately 100 MHz PL clock, and DMA IRQ affinities restored after each run. See before/restored JSON evidence.','',
'## Warm latency','',
'| Audio | Pairs | CPU p50 | CPU p95 | FPGA p50 | FPGA p95 | p50 speedup | FPGA real-time factor |',
'|---|---:|---:|---:|---:|---:|---:|---:|']
for r in summary['results']:
    c,p=r['metrics']['cpu'],r['metrics']['fpga']
    lines.append(f"| {r['audio_seconds']:g} s | {r['runs']} | {c['p50_ms']:.3f} ms | {c['p95_ms']:.3f} ms | {p['p50_ms']:.3f} ms | {p['p95_ms']:.3f} ms | {r['speedup_p50']:.3f}x | {p['rtf_p50']:.4f} |")
lines += ['',
'Measured frontend + model execution + greedy decode on the same board. WAV file reading, graph/session initialization, FPGA app changes, and numerical verification are outside timed calls. The CPU uses the duration-specific optimized policies shipped in `config/policies.json`; the FPGA uses its shipped selected policy. Main thread affinity is CPU 3, FPGA DMA IRQ affinity CPU 2. CPU/FPGA order alternates, with 10 unmeasured warmup pairs per duration. Percentiles use NumPy default linear interpolation. No measured samples were removed. Speedup is CPU p50 divided by FPGA p50, rather than the median of per-pair ratios.','',
'## Public command startup and first calls','',
f"The one-second public smoke test took {smoke['initialization_seconds']:.3f} s to initialize. Its first physical call took {smoke['cold']['seconds']:.3f} s. The three subsequent calls were "+', '.join(f"{r['seconds']*1000:.3f} ms" for r in smoke['warm_runs'])+f"; median {smoke['warm_p50_seconds']*1000:.3f} ms.",
'',
'The first warm call had a large frontend outlier. These startup results are retained as observed and are separate from the sustained warmed measurements. Cold calls are not suitable evidence for an interactive startup latency claim. Individual stage times, additional benchmark cold calls, raw pairs, and environment snapshots are included in the JSON evidence.','',
'The captured kernel log contains device-tree overlay removal warnings about possible memory leaks. Inference, input rejection and rollback all completed successfully; this test does not qualify indefinite repeated overlay switching.','',
'## Use the installed MVP','',
'```sh',
'cd /home/ubuntu/kv260-asr-mvp-20261015',
'sudo .venv/bin/python scripts/run_board.py -- reports/test-inputs/speech_10.wav --runs 3 --verify-cpu --out reports/local/my-result.json',
'```','',
'Use a new output filename each time. Replace the WAV with an uncompressed 16 kHz mono PCM16, PCM24 or PCM32 recording of 320–40,959 samples. The command restores the supported bulk starting state on exit.','',
'To repeat the sustained comparison:','',
'```sh',
'sudo .venv/bin/python reports/benchmark_mvp.py --root "$PWD" --runs 300',
'```','',
'This benchmark overwrites its own comparison evidence. Copy `reports/comparison` first if retaining earlier measurements.','',
'## Scope and evidence','',
'The three inputs are prefixes of one existing speech recording. Results establish numerical agreement and performance for these inputs; they do not establish representative word error rate. Live microphone transcription, streaming behavior and longer inputs remain outside the documented MVP qualification. No power or energy measurement was taken.','',
'- `comparison.csv`: summary metrics.',
'- `paired-runs.csv`: all 900 measured pairs in spreadsheet-ready form.',
'- `board-reports/comparison/`: raw rows, timing stages, counters, policies, environment and rollback states.',
'- `board-reports/local/`: installation, package lock, unit-test, public smoke and hardware test logs.',
'- `benchmark_mvp.py`: reproducible harness using the unchanged project runtime.',
'- `source.zip`: source and test-input package sent to the board.',
'- `board-reports/local/archive-sha256.txt`: deployed source/archive hashes.','']
(folder/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
print('\n'.join(lines[:30]))
