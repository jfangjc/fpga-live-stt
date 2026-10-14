"""Resolve CPU timing variation after all preceding board runs finish."""
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = '/home/ubuntu/prototype-v3-fused'
HOST = 'ubuntu@192.168.1.111'
PASSWORD = os.environ['ASR_KV260_PASSWORD']
OPTIONS = ['-batch', '-hostkey', 'SHA256:LKipAYiol8maTkeoe4VDOwZRuJLRLhyp1Nd7iSMk+1I', '-pw', PASSWORD]
PLINK = 'C:/Program Files/PuTTY/plink.exe'
PSCP = 'C:/Program Files/PuTTY/pscp.exe'
package = Path('C:/Users/jfang/Downloads/FPGA-ASR-DSP-input-register-vector-maskfast-confirmed-2026-10-14/package.json')
deadline = time.monotonic()+8*3600
while True:
    try:
        saved = json.loads(package.read_text())
        if saved['verified']: break
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        pass
    error = ROOT/'build/branch512_ab166_neon_maskfast_qualification_error.log'
    if error.exists() and 'Traceback (most recent call last)' in error.read_text(errors='replace'):
        raise RuntimeError('Prior board qualification failed; isolated CPU measurement not started')
    if time.monotonic() > deadline: raise TimeoutError('Prior board work incomplete')
    time.sleep(5)
label = 'branch512_ab166_cpu_isolated_confirmation'
command = f'cd {REMOTE} && printf "%s\\n" {shlex.quote(PASSWORD)} | sudo -S sh scripts/run_branch512_ab166_board.sh software/latency/confirm_branch512_ab166_cpu_isolated.py --runs 100 --out reports/fused/{label}.json > reports/fused/{label}.log 2>&1'
result = subprocess.run([PLINK, *OPTIONS, HOST, command], cwd=ROOT)
if result.returncode: raise RuntimeError('Isolated CPU benchmark failed')
for suffix in ('json', 'log'):
    result = subprocess.run([PSCP, *OPTIONS, f'{HOST}:{REMOTE}/reports/fused/{label}.{suffix}', str(ROOT/'reports/fused')], cwd=ROOT)
    if result.returncode: raise RuntimeError('Isolated CPU result download failed')
report = json.loads((ROOT/f'reports/fused/{label}.json').read_text())
assert report['complete'] and not report['hardware_execution'] and not report['fpga_session_loaded']
hybrid = json.loads((ROOT/'reports/fused/branch512_ab166_neon_maskfast_latency_confirmation.json').read_text())
comparisons = []
for cpu in report['contexts']:
    fpga = next(c for c in hybrid['contexts'] if c['context_seconds'] == cpu['context_seconds'])
    baseline = min(cpu['cpu_p50'], fpga['cpu_p50'])
    comparisons.append({'context_seconds': cpu['context_seconds'], 'isolated_cpu_p50': cpu['cpu_p50'],
                        'paired_cpu_p50': fpga['cpu_p50'], 'hybrid_p50': fpga['fpga_p50'],
                        'speedup_against_faster_cpu': baseline/fpga['fpga_p50'],
                        'meets_50_percent': fpga['fpga_p50'] <= .5*baseline and fpga['fpga_p95'] < min(cpu['cpu_p95'], fpga['cpu_p95'])})
print(json.dumps({'complete': True, 'cpu_isolation_comparison': comparisons,
                  'twofold_speed_acceptance_with_isolated_cpu': all(c['meets_50_percent'] for c in comparisons)}), flush=True)
(ROOT/'reports/fused/branch512_ab166_cpu_isolation_comparison.json').write_text(json.dumps({'complete': True, 'comparisons': comparisons}, indent=2)+'\n')
