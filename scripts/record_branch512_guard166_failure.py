"""Freeze the failed full-route proof separately from any later repair reports."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
paths=[]
for source,name in ((ROOT/'build/branch512_guard166_implement_driver.log','driver.log'),
                    (ROOT/'reports/fused/branch512_guard166_system_timing.rpt','timing.rpt'),
                    (ROOT/'reports/fused/branch512_guard166_system_drc.rpt','drc.rpt')):
    dest=ROOT/'reports/fused'/('branch512_guard166_fullroute_failed_'+name)
    data=source.read_bytes()
    if dest.exists():assert dest.read_bytes()==data
    else:dest.write_bytes(data)
    paths.append(dest)
data=paths[0].read_bytes()
text=data.decode('utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8')
assert any(line.strip()=='Chain timing or DRC gate failed' for line in text.splitlines())
timing=paths[1].read_text()
setup=float(re.search(r'Setup\s*:\s*\d+\s+Failing Endpoints,\s+Worst Slack\s+([-\d.]+)ns',timing)[1])
hold=float(re.search(r'Hold\s*:\s*\d+\s+Failing Endpoints,\s+Worst Slack\s+([-\d.]+)ns',timing)[1])
assert setup<.001 and hold>=0
assert 'engine/pointwise/input_memory' in timing and 'mac/DSP_M_DATA_INST' in timing
assert not (ROOT/'reports/fused/branch512_guard166_system_implementation.json').exists()
paths += [ROOT/'build/branch512_guard166_system/Prototype_v3_branch512_guard166.runs/impl_1/asr_v2_top_routed.dcp',
          ROOT/'reports/fused/branch512_guard_regression_evidence.json',Path(__file__)]
record={'complete':True,'qualified':False,'hardware_execution':False,'deployment_started':False,
        'clock_hz':166666666,'setup_slack_ns':setup,'hold_slack_ns':hold,
        'worst_path':'Pointwise input BRAM through multiplication to DSP product register',
        'sources_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
dest=ROOT/'reports/fused/branch512_guard166_fullroute_failure.json'
if dest.exists():assert json.loads(dest.read_text())==record
else:dest.write_text(json.dumps(record,indent=2)+'\n')
print('PASS: failed final full-route timing and routed checkpoint preserved separately')
