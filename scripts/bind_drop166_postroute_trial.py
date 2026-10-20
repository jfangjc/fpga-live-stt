"""Bind a completed, non-deploying post-route timing trial to its checkpoint."""
import argparse,hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--aggressive',action='store_true');args=ap.parse_args()
prefix='branch512_drop166_postroute'+('_aggressive' if args.aggressive else '')
folder=prefix+'_repair'
script='branch512_drop166_postroute'+('_aggressive' if args.aggressive else '')+'_probe.tcl'
trial=ROOT/'reports/fused'/(prefix+'_trial.json');record=json.loads(trial.read_text())
assert record['complete'] and not record['hardware_execution'] and not record['firmware_exported']
assert record['directive']==('AggressiveExplore' if args.aggressive else 'Explore')
timing=ROOT/'reports/fused'/(prefix+'_timing.rpt')
text=timing.read_text()
setup=float(re.search(r'Setup\s*:\s*\d+\s+Failing Endpoints,\s+Worst Slack\s+([-\d.]+)ns',text)[1])
hold=float(re.search(r'Hold\s*:\s*\d+\s+Failing Endpoints,\s+Worst Slack\s+([-\d.]+)ns',text)[1])
assert setup==record['setup_slack_ns'] and hold==record['hold_slack_ns']
assert record['timing_acceptance']==(setup>=.001 and hold>=0 and record['error_or_critical_drc_count']==0)
log=ROOT/'build'/(prefix+'_driver.log');data=log.read_bytes()
logtext=data.decode('utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8')
assert 'phys_opt_design completed successfully' in logtext and not re.search(r'^ERROR:',logtext,re.M)
assert any(line.startswith('DROP166_POSTROUTE_TRIAL_COMPLETE timing_acceptance=') for line in logtext.splitlines())
parent=ROOT/'reports/fused'/('branch512_drop166_postroute_evidence.json' if args.aggressive else 'branch512_drop166_fullroute_failure.json')
parent_record=json.loads(parent.read_text());assert parent_record['complete']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for name,value in parent_record['sources_sha256'].items():assert sha(ROOT/name)==value,name
paths=[trial,timing,log,parent,ROOT/'scripts'/script,Path(__file__),ROOT/'build'/folder/'asr_v2_top.dcp']
paths += [ROOT/'reports/fused'/(prefix+'_'+suffix+'.rpt') for suffix in ('before','paths','drc','status')]
paths += [ROOT/name for name in parent_record['sources_sha256']]
record.update(clock_hz=166666666,pointwise_macs=512,depthwise_macs=64,
              sources_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in paths})
dest=ROOT/'reports/fused'/(prefix+'_evidence.json')
if dest.exists():assert json.loads(dest.read_text())==record
else:dest.write_text(json.dumps(record,indent=2)+'\n')
print('PASS: completed',record['directive'],'post-route trial bound; timing acceptance',record['timing_acceptance'])
