"""Start isolated implementation only after published synthesis and simulation passes."""
import argparse,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--wait-seconds',type=int,default=3600);a=ap.parse_args()
deadline=time.monotonic()+a.wait_seconds;last=None
while True:
    logs=[]
    for name in ('short_wide_sim.log','short_wide_synth.log'):
        path=ROOT/'reports/fused'/name;logs.append(path.read_text(errors='replace') if path.exists() else '')
    ready=('PASS: 64 short-cache retained pair arithmetic' in logs[0],'SHORT_WIDE_SYNTH_COMPLETE' in logs[1])
    if ready!=last:print(f'Simulation complete: {ready[0]}; synthesis complete: {ready[1]}',flush=True);last=ready
    if all(ready):break
    if any('\nERROR:' in log for log in logs):raise RuntimeError('Build log reports an error; implementation remains gated')
    if time.monotonic()>deadline:raise TimeoutError('Waiting for simulation/synthesis; existing jobs were left intact')
    time.sleep(5)
subprocess.run([os.sys.executable,str(ROOT/'scripts/check_short_wide_build.py')],check=True,cwd=ROOT)
environment=os.environ.copy()
for name in ('PYTHONHOME','PYTHONPATH'):environment.pop(name,None)
print('Starting separately gated 100 MHz wider-depthwise implementation',flush=True)
subprocess.run(['C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat','-mode','batch','-source','scripts/short_wide_implement.tcl',
                '-log','reports/fused/short_wide_implementation.log','-journal','build/short_wide_implementation.jou'],
               cwd=ROOT,env=environment,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
print('Wider-depthwise implementation command completed',flush=True)
