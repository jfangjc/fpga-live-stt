"""Bind the preserved near-timing routed layout as a reuse reference only."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
reference=ROOT/'build/branch512_outslice166_system/Prototype_v3_branch512_outslice166.runs/impl_1/asr_v2_top_routed.dcp'
failure=ROOT/'reports/fused/branch512_outslice166_timing_failure.json'
parent=json.loads(failure.read_text())
assert parent['complete'] and not parent['qualified'] and not parent['deployment_started']
assert parent['clock_hz']==166666666 and parent['setup_slack_ns']>=-.250 and parent['hold_slack_ns']>=0
assert reference.is_file() and reference.stat().st_size>1000000
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
proof={'complete':True,'hardware_execution':False,'reference_qualified_for_deployment':False,
       'reference_purpose':'Reuse unchanged placement/routing for the exact DW stage change; new timing/parity gates remain mandatory',
       'incremental_directive':'TimingClosure','clock_hz':166666666,
       'reference_setup_slack_ns':parent['setup_slack_ns'],'reference_hold_slack_ns':parent['hold_slack_ns'],
       'sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in (reference,failure,Path(__file__))},
       'documentation':'https://docs.amd.com/r/en-US/ug904-vivado-implementation/Using-Incremental-Implementation-in-Project-Mode'}
dest=ROOT/'reports/fused/branch512_drop166_incremental_reference.json'
if dest.exists():assert json.loads(dest.read_text())==proof,'Reference changed after binding'
else:dest.write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: preserved routed reference bound; new final timing gates are required')
