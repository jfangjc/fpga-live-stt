"""Independently audit completed evidence and preserve an accepted 2x result."""
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = Path('C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')
label = 'branch512_ab166_neon_maskfast'
report = ROOT/f'reports/fused/{label}_latency_confirmation.json'
deadline = time.monotonic()+8*3600
while True:
    try:
        evidence = json.loads(report.read_text())
        if evidence['complete'] and evidence['hardware_execution']:
            break
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        pass
    error = ROOT/f'build/{label}_qualification_error.log'
    if error.exists() and 'Traceback (most recent call last)' in error.read_text(errors='replace'):
        raise RuntimeError('Combined qualification failed; no accepted result archived')
    if time.monotonic() > deadline:
        raise TimeoutError('Combined qualification incomplete; no acceptance claim')
    time.sleep(5)
# The qualification job downloads graphs and logs after its result JSON. Wait
# for its verified package before auditing/archiving the complete artifact set.
package = Path('C:/Users/jfang/Downloads/FPGA-ASR-DSP-input-register-vector-maskfast-confirmed-2026-10-14/package.json')
while True:
    try:
        saved = json.loads(package.read_text())
        if saved['verified'] and Path(saved['selected_report']) == report:
            break
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        pass
    error = ROOT/f'build/{label}_qualification_error.log'
    if error.exists() and 'Traceback (most recent call last)' in error.read_text(errors='replace'):
        raise RuntimeError('Combined preservation failed; no accepted result archived')
    if time.monotonic() > deadline:
        raise TimeoutError('Combined preservation incomplete; no acceptance claim')
    time.sleep(5)
subprocess.run([str(PY), '-I', 'scripts/audit_branch512_ab166_combined.py'], cwd=ROOT, check=True)
audit = json.loads((ROOT/f'reports/fused/{label}_acceptance_audit.json').read_text())
if audit['twofold_speed_acceptance']:
    subprocess.run([str(PY), '-I', 'scripts/save_latency20_work.py', '--destination',
                    'C:/Users/jfang/Downloads/FPGA-ASR-2x-combined-confirmed-2026-10-14',
                    '--result', str(report)], cwd=ROOT, check=True)
else:
    print('Evidence audited; 2x not achieved across all three contexts. Goal remains active.', flush=True)
