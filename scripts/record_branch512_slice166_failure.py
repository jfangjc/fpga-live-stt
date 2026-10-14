"""Preserve the authoritative failed route and prevent latency claims."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
timing=ROOT/'reports/fused/branch512_slice166_system_timing.rpt'
log=ROOT/'build/branch512_slice166_implement_driver.log'
log_bytes=log.read_bytes()
log_text=log_bytes.decode('utf-16' if log_bytes.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8',errors='replace')
assert 'Chain timing or DRC gate failed' in log_text
text=timing.read_text()
setup=float(re.search(r'Setup\s*:\s*\d+\s+Failing Endpoints,\s+Worst Slack\s+([-\d.]+)ns',text)[1])
hold=float(re.search(r'Hold\s*:\s*\d+\s+Failing Endpoints,\s+Worst Slack\s+([-\d.]+)ns',text)[1])
assert setup<.001 or hold<0
paths=[timing,log,ROOT/'reports/fused/branch512_slice_regression_evidence.json',ROOT/'rtl/experimental/qn_branch512_slice_axis.sv']
report={'complete':True,'qualified':False,'hardware_execution':False,'clock_hz':166666666,
        'setup_slack_ns':setup,'hold_slack_ns':hold,'deployment_started':False,
        'reason':'Routed timing gate failed; no qualified export or physical latency result',
        'worst_path':'Pointwise DSP output to outer sequencer step register enable',
        'next_experiment':'Separate elastic output register with retained completion handshake',
        'sources_and_reports_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
(ROOT/'reports/fused/branch512_slice166_timing_failure.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
