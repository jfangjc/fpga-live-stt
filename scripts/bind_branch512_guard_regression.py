"""Source-bind header equivalence and independent block/reset regressions."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
exec((ROOT/'scripts/check_branch512_drop_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_branch512_drop_software.py')})
proof_path=ROOT/'reports/fused/branch512_header_guard_equivalence.json'
proof=json.loads(proof_path.read_text())
assert proof['complete'] and proof['binary_header_acceptance_unchanged']
assert proof['all_hk_ht_combinations_covered']==2**32
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for name,value in proof['sources_sha256'].items():assert sha(ROOT/name)==value,name
assert (ROOT/'rtl/experimental/qn_branch512_guard_axis.sv').read_text()==(ROOT/'rtl/experimental/qn_branch512_drop_axis.sv').read_text().replace('qn_branch512_drop_inner','qn_branch512_guard_inner')
paths=[proof_path,ROOT/'reports/fused/branch512_drop_regression_evidence.json']
for variant,marker in (('fast','PASS: 25 two-output residual branches'),
                       ('reset','PASS: 6 full-pipeline reset/replay cases'),
                       ('payload_reset','PASS: 2 full output-data buffer reset/replay cases')):
    path=ROOT/f'build/branch512_guard_{variant}_sim/branch512_guard_{variant}_sim.sim/sim_1/behav/xsim/simulate.log'
    text=path.read_text();assert marker in text and not re.search(r'Fatal:|ERROR:|cannot be opened for reading',text),variant
    paths += [path,ROOT/f'scripts/branch512_guard_{variant}_sim.tcl']
paths += [ROOT/'rtl/experimental'/name for name in ('qn_branch512_guard_inner.sv','qn_branch512_guard_axis.sv')]
paths += [ROOT/f'sim/tb_qn_branch512_guard_{kind}.sv' for kind in ('axis','reset','payload_reset')]
paths += [ROOT/'scripts/create_branch512_guard.py',Path(__file__)]+[ROOT/name for name in proof['sources_sha256']]
record={'complete':True,'hardware_execution':False,'pointwise_macs':512,'depthwise_macs':64,
        'full_blocks_checked':25,'full_reset_replay_cases':8,
        'header_acceptance_unchanged':True,'datapath_and_handshake_unchanged':True,
        'sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}}
dest=ROOT/'reports/fused/branch512_guard_regression_evidence.json'
if dest.exists():assert json.loads(dest.read_text())==record
else:dest.write_text(json.dumps(record,indent=2)+'\n')
print('PASS: exact redundant header guard removal, 25 full blocks and eight reset/replay cases bound')
