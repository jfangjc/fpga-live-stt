"""Qualify extra retention only after the base candidate finishes board tests."""
import json,os,shlex,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REMOTE='/home/ubuntu/prototype-v3-fused';HOST='ubuntu@192.168.1.111'
KEY='SHA256:LKipAYiol8maTkeoe4VDOwZRuJLRLhyp1Nd7iSMk+1I'
PASSWORD=os.environ['ASR_KV260_PASSWORD']
OPTIONS=['-batch','-hostkey',KEY,'-pw',PASSWORD]
PLINK=Path('C:/Program Files/PuTTY/plink.exe');PSCP=Path('C:/Program Files/PuTTY/pscp.exe')
PY=Path('C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')
def read_log(path):
    data=path.read_bytes()
    return data.decode('utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8',errors='replace')

def timing_failed(path):
    # Tcl echoes gate commands; only actual error lines indicate failure.
    return any(line.strip()=='Chain timing or DRC gate failed' or line.lstrip().startswith('ERROR:')
               for line in read_log(path).splitlines())

def local(args):
    result=subprocess.run([str(x) for x in args],cwd=ROOT)
    if result.returncode:raise RuntimeError(f'Tool {Path(args[0]).name} failed with exit code {result.returncode}')
def download(pattern):local([PSCP,*OPTIONS,f'{HOST}:{REMOTE}/{pattern}',ROOT/'reports/fused'])
def physical(script,arguments,label):
    command=f'cd {REMOTE} && printf "%s\\n" {shlex.quote(PASSWORD)} | sudo -S sh scripts/run_branch512_ab166_board.sh software/latency/{script} {arguments} > reports/fused/{label}.log 2>&1'
    local([PLINK,*OPTIONS,HOST,command])
    download(f'reports/fused/{label}.json')
    p=json.loads((ROOT/f'reports/fused/{label}.json').read_text())
    assert p['complete'] and p['hardware_execution']
    print('COMPLETE:',label,flush=True)
    return p

deadline=time.monotonic()+8*3600
# Wait for the existing scalar maskfast job; never overlap board measurements.
while True:
    path=ROOT/'reports/fused/branch512_ab166_maskfast_latency_confirmation.json'
    try:
        preceding=json.loads(path.read_text())
        if preceding['complete'] and preceding['hardware_execution']:break
    except (FileNotFoundError,json.JSONDecodeError,PermissionError):pass
    error=ROOT/'build/branch512_ab166_maskfast_qualification_error.log'
    if error.exists() and 'Traceback (most recent call last)' in read_log(error):
        raise RuntimeError('Scalar maskfast qualification failed; combined board tests not started')
    if time.monotonic()>deadline:raise TimeoutError('Preceding board qualification incomplete')
    time.sleep(5)
cpu=json.loads((ROOT/'reports/fused/branch512_ab166_cpu_policy_wide.json').read_text())
assert cpu['complete'] and cpu['candidate_count']==64 and cpu['all_warm_logits_bit_exact']
download('reports/fused/branch512_more_pool_oracle.json')
download('reports/fused/branch512_more_pool_oracle.log')
download('reports/fused/branch512_cpu_pool_policy_clean.json')
download('reports/fused/branch512_cpu_pool_policy_clean.log')
local([PY,'-I','software/latency/check_more_model_evidence.py'])
# FPGA arithmetic, protocol and library are unchanged from more; revalidate full model with the new CPU tail.
p=physical('validate_branch512_ab166_neon_maskfast_physical.py','--out reports/fused/branch512_ab166_neon_maskfast_physical_validation.json','branch512_ab166_neon_maskfast_physical_validation')
assert len(p['clips'])==36 and all(c['physical_oracle_bit_exact'] for c in p['clips'])
physical('tune_branch512_ab166_neon_maskfast_policy.py','--runs 30 --out reports/fused/branch512_ab166_neon_maskfast_latency_policy.json','branch512_ab166_neon_maskfast_latency_policy')
physical('confirm_branch512_ab166_neon_maskfast_latency.py','--policy reports/fused/branch512_ab166_neon_maskfast_latency_policy.json --runs 300 --out reports/fused/branch512_ab166_neon_maskfast_latency_confirmation.json','branch512_ab166_neon_maskfast_latency_confirmation')
download('reports/fused/branch512_ab166_neon_maskfast*.json')
download('reports/fused/branch512_ab166_neon_maskfast*.log')
download('reports/fused/branch512_ab166_neon_maskfast*.onnx')
local([PY,'-I','scripts/analyze_stream_latency.py','reports/fused/branch512_ab166_neon_maskfast_latency_confirmation.json','--out','reports/fused/branch512_ab166_neon_maskfast_latency_costs.json'])
report=json.loads((ROOT/'reports/fused/branch512_ab166_neon_maskfast_latency_confirmation.json').read_text())
print(json.dumps({'complete':True,'twofold_speed_acceptance':report['twofold_speed_acceptance'],
 'contexts':[{k:c[k] for k in ('context_seconds','cpu_p50','fpga_p50','cpu_p95','fpga_p95','speedup_factor','latency_reduction_percent')} for c in report['contexts']]}),flush=True)

local([PY,'-I','scripts/save_latency20_work.py','--destination',Path('C:/Users/jfang/Downloads/FPGA-ASR-DSP-input-register-vector-maskfast-confirmed-2026-10-14'),'--result','reports/fused/branch512_ab166_neon_maskfast_latency_confirmation.json'])
