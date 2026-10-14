"""Fair full-path valid-frame trial on an explicitly selected qualified app."""
import argparse
import json
import os
import shlex
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--platform',choices=('branch512_ab166','branch512_dma128166'),required=True)
a=ap.parse_args();label=a.platform+'_vf'
HOST='ubuntu@192.168.1.111';REMOTE='/home/ubuntu/prototype-v3-fused'
PASSWORD=os.environ['ASR_KV260_PASSWORD']
OPTIONS=['-batch','-hostkey','SHA256:LKipAYiol8maTkeoe4VDOwZRuJLRLhyp1Nd7iSMk+1I','-pw',PASSWORD]
PLINK='C:/Program Files/PuTTY/plink.exe';PSCP='C:/Program Files/PuTTY/pscp.exe'
PY='C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
def local(args):
    p=subprocess.run([str(v) for v in args],cwd=ROOT)
    if p.returncode:raise RuntimeError(f'{Path(args[0]).name} failed with exit code {p.returncode}')
def download(pattern):local([PSCP,*OPTIONS,f'{HOST}:{REMOTE}/{pattern}',ROOT/'reports/fused'])
def run(script,arguments,result,hardware):
    command=f'cd {REMOTE} && printf "%s\\n" {shlex.quote(PASSWORD)} | sudo -S sh scripts/run_{a.platform}_board.sh software/latency/{script} {arguments} > reports/fused/{result}.log 2>&1'
    local([PLINK,*OPTIONS,HOST,command]);download(f'reports/fused/{result}.json');download(f'reports/fused/{result}.log')
    p=json.loads((ROOT/f'reports/fused/{result}.json').read_text())
    assert p['complete'] and p['hardware_execution']==hardware
    print('COMPLETE:',result,flush=True)
    return p
# These CPU phases load no FPGA sessions. They use the same board harness and
# restoration discipline as the physical comparisons.
run('tune_valid_frame_cpu.py','--runs 30 --out reports/fused/valid_frame_cpu_policy.json','valid_frame_cpu_policy',False)
run('confirm_valid_frame_cpu_isolated.py','--runs 100 --out reports/fused/valid_frame_cpu_isolated_confirmation.json','valid_frame_cpu_isolated_confirmation',False)
parity=run(f'validate_{label}_physical.py',f'--out reports/fused/{label}_physical_validation.json',f'{label}_physical_validation',True)
assert len(parity['clips'])==36 and all(c['physical_oracle_bit_exact'] for c in parity['clips'])
run(f'tune_{label}_policy.py',f'--runs 30 --out reports/fused/{label}_latency_policy.json',f'{label}_latency_policy',True)
result=run(f'confirm_{label}_latency.py',f'--policy reports/fused/{label}_latency_policy.json --runs 300 --out reports/fused/{label}_latency_confirmation.json',f'{label}_latency_confirmation',True)
download(f'reports/fused/{label}*.onnx')
local([PY,'-I','scripts/analyze_stream_latency.py',f'reports/fused/{label}_latency_confirmation.json','--out',f'reports/fused/{label}_latency_costs.json'])
print(json.dumps({'complete':True,'twofold_speed_acceptance':result['twofold_speed_acceptance'],
                 'contexts':[{k:c[k] for k in ('context_seconds','fpga_p50','strongest_cpu_p50','speedup_against_strongest_cpu','meets_50_percent')} for c in result['contexts']]}),flush=True)
local([PY,'-I','scripts/save_latency20_work.py','--destination',f'C:/Users/jfang/Downloads/FPGA-ASR-{a.platform}-valid-frame-confirmed-2026-10-15','--result',f'reports/fused/{label}_latency_confirmation.json'])
