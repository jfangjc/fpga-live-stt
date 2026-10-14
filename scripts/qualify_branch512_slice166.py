"""One-off gated build-to-board qualification. Password comes only from environment."""
import hashlib,json,os,shlex,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
APP='asr-v3-branch512-slice166';REMOTE='/home/ubuntu/prototype-v3-fused'
HOST='ubuntu@192.168.1.111';KEY='SHA256:LKipAYiol8maTkeoe4VDOwZRuJLRLhyp1Nd7iSMk+1I'
PY=Path('C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')
PASSWORD=os.environ['ASR_KV260_PASSWORD']
OPTIONS=['-batch','-hostkey',KEY,'-pw',PASSWORD]
PLINK=Path('C:/Program Files/PuTTY/plink.exe');PSCP=Path('C:/Program Files/PuTTY/pscp.exe')
def local(args,cwd=ROOT):
    result=subprocess.run([str(a) for a in args],cwd=cwd)
    if result.returncode:raise RuntimeError(f'Tool {Path(args[0]).name} failed with exit code {result.returncode}')
def ssh(command):local([PLINK,*OPTIONS,HOST,command])
def upload(path,destination):local([PSCP,*OPTIONS,str(path),f'{HOST}:{REMOTE}/{destination}'])
def download(pattern,destination):local([PSCP,*OPTIONS,f'{HOST}:{REMOTE}/{pattern}',destination])
def physical(script,arguments,label):
    # Every harness invocation restores the accepted bulk app and 100 MHz clock.
    command=f'cd {REMOTE} && printf "%s\\n" {shlex.quote(PASSWORD)} | sudo -S sh scripts/run_branch512_slice166_board.sh software/latency/{script} {arguments} > reports/fused/{label}.log 2>&1'
    ssh(command)
    download(f'reports/fused/{label}.json',ROOT/'reports/fused')
    report=json.loads((ROOT/f'reports/fused/{label}.json').read_text())
    assert report['complete'] and report['hardware_execution']
    print('COMPLETE:',label,flush=True)
timing=ROOT/'reports/fused/branch512_slice166_system_implementation.json'
deadline=time.monotonic()+6*3600
while not timing.exists():
    log=ROOT/'build/branch512_slice166_implement_driver.log'
    if log.exists() and any((line.startswith('ERROR:') or 'Chain timing or DRC gate failed' in line) for line in log.read_text(errors='replace').splitlines()):
        raise RuntimeError('Routed implementation failed; board deployment was not started')
    if time.monotonic()>deadline:raise TimeoutError('No routed timing proof; board deployment was not started')
    time.sleep(5)
time.sleep(1) # Allow the atomic tool-side file close to finish.
proof=json.loads(timing.read_text())
assert proof['clock_hz']==166666666 and proof['pointwise_macs']==512
assert proof['setup_slack_ns']>=.001 and proof['hold_slack_ns']>=0
local([PY,'-I','scripts/prepare_branch512_slice166_firmware.py'])
directory=ROOT/'deployment'/APP
local(['C:/AMDDesignTools/2026.1/Vivado/bin/bootgen.bat','-arch','zynqmp','-image','boot.bif','-w','-o',APP+'.bit.bin'],directory)
local([PSCP,*OPTIONS,'-r',directory,f'{HOST}:{REMOTE}/deployment/'])
upload(ROOT/'reports/fused/branch512_slice166_firmware_evidence.json','reports/fused/')
command=f'cd {REMOTE} && dtc -@ -I dts -O dtb -o deployment/{APP}/{APP}.dtbo deployment/{APP}/{APP}.dts && .venv/bin/python scripts/finalize_branch512_slice166_firmware.py && printf "%s\\n" {shlex.quote(PASSWORD)} | sudo -S .venv/bin/python scripts/install_branch512_slice166_firmware.py'
ssh(command)
download('reports/fused/branch512_slice166_firmware_evidence.json',ROOT/'reports/fused')
download(f'deployment/{APP}/{APP}.dtbo',directory)
physical('test_branch512_slice166_blocks.py','','branch512_slice166_physical_blocks')
blocks=json.loads((ROOT/'reports/fused/branch512_slice166_physical_blocks.json').read_text())
assert blocks['all_outputs_bit_exact'] and len(blocks['cases'])==294
physical('validate_branch512_slice166_physical.py','--out reports/fused/branch512_slice166_physical_validation.json','branch512_slice166_physical_validation')
parity=json.loads((ROOT/'reports/fused/branch512_slice166_physical_validation.json').read_text())
assert len(parity['clips'])==36 and all(row['physical_oracle_bit_exact'] for row in parity['clips'])
physical('tune_branch512_slice166_policy.py','--runs 30 --out reports/fused/branch512_slice166_latency_policy.json','branch512_slice166_latency_policy')
physical('confirm_branch512_slice166_latency.py','--policy reports/fused/branch512_slice166_latency_policy.json --runs 300 --out reports/fused/branch512_slice166_latency_confirmation.json','branch512_slice166_latency_confirmation')
download('reports/fused/branch512_slice166*.json',ROOT/'reports/fused')
download('reports/fused/branch512_slice166*.log',ROOT/'reports/fused')
download('reports/fused/branch512_slice166*.onnx',ROOT/'reports/fused')
local([PY,'-I','scripts/analyze_stream_latency.py','reports/fused/branch512_slice166_latency_confirmation.json','--out','reports/fused/branch512_slice166_latency_costs.json'])
report=json.loads((ROOT/'reports/fused/branch512_slice166_latency_confirmation.json').read_text())
print(json.dumps({'complete':True,'twofold_speed_acceptance':report['twofold_speed_acceptance'],
                 'contexts':[{k:c[k] for k in ('context_seconds','cpu_p50','fpga_p50','cpu_p95','fpga_p95','speedup_factor','latency_reduction_percent')} for c in report['contexts']]}),flush=True)
