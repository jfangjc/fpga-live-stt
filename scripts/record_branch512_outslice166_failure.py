"""Preserve final failed timing and the observed DW quantizer path."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
timing=ROOT/'reports/fused/branch512_outslice166_system_timing.rpt'
log=ROOT/'build/branch512_outslice166_implement_driver.log'
data=log.read_bytes();text=data.decode('utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8',errors='replace')
assert any(line.strip()=='Chain timing or DRC gate failed' for line in text.splitlines())
report=timing.read_text()
setup=float(re.search(r'Setup\s*:\s*\d+\s+Failing Endpoints,\s+Worst Slack\s+([-\d.]+)ns',report)[1])
hold=float(re.search(r'Hold\s*:\s*\d+\s+Failing Endpoints,\s+Worst Slack\s+([-\d.]+)ns',report)[1])
assert setup<.001 and hold>=0
assert not (ROOT/'reports/fused/branch512_outslice166_system_implementation.json').exists()
paths=[timing,log,ROOT/'reports/fused/branch512_outslice166_system_drc.rpt',ROOT/'reports/fused/branch512_outslice_regression_evidence.json',Path(__file__)]
record={'complete':True,'qualified':False,'hardware_execution':False,'deployment_started':False,
        'clock_hz':166666666,'setup_slack_ns':setup,'hold_slack_ns':hold,
        'reason':'Final routed setup gate failed; no qualified XSA or board deployment',
        'worst_path':'Depthwise compact quantizer shifts[4] to integer_result register',
        'next_experiment':'Private exact DW quantizer with an elastic effective-drop stage',
        'sources_and_reports_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
(ROOT/'reports/fused/branch512_outslice166_timing_failure.json').write_text(json.dumps(record,indent=2)+'\n')
print('Preserved final setup',setup,'hold',hold,'failure; no deployment')
