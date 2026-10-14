"""Bind real DSP equivalence and full-block regressions for input retiming."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
exec((ROOT/'scripts/check_branch512_guard_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_branch512_guard_software.py')})
old=(ROOT/'rtl/experimental/qn_branch512_slice_pw_core.v').read_text()
new=(ROOT/'rtl/experimental/qn_branch512_ab_pw_core.v').read_text()
expected=old.replace('qn_branch512_slice_pw_core','qn_branch512_ab_pw_core')
changes={'.AREG(0),.ACASCREG(0),.BREG(0),.BCASCREG(0)':'.AREG(1),.ACASCREG(1),.BREG(1),.BCASCREG(1)',
         '.MREG(1),.PREG(1)':'.MREG(0),.PREG(1)',
         ".CEA2(1'b0),.CEB1(1'b0),.CEB2(1'b0)": ".CEA2(read_valid),.CEB1(1'b0),.CEB2(read_valid)",
         ".RSTA(1'b0),.RSTB(1'b0)":'.RSTA(!aresetn),.RSTB(!aresetn)'}
for a,b in changes.items():assert expected.count(a)==1;expected=expected.replace(a,b)
assert new==expected,'Unexpected datapath/controller change'
assert (ROOT/'sim/fast/qn_branch512_ab_pw_core.v').read_text()==new.replace('DSP48E2 #(','qn_mac_ab_model #(')
assert (ROOT/'rtl/experimental/qn_branch512_ab_inner.sv').read_text()==(ROOT/'rtl/experimental/qn_branch512_guard_inner.sv').read_text().replace('qn_branch512_guard_inner','qn_branch512_ab_inner').replace('qn_branch512_slice_pw_core','qn_branch512_ab_pw_core')
assert (ROOT/'rtl/experimental/qn_branch512_ab_axis.sv').read_text()==(ROOT/'rtl/experimental/qn_branch512_guard_axis.sv').read_text().replace('qn_branch512_guard_inner','qn_branch512_ab_inner')
paths=[]
for variant,marker in (('ab_mac_conformance','PASS: 203980 old/new vendor DSP and model checks'),
                       ('branch512_ab_fast_sim','PASS: 25 two-output residual branches'),
                       ('branch512_ab_reset_sim','PASS: 6 full-pipeline reset/replay cases'),
                       ('branch512_ab_payload_reset_sim','PASS: 2 full output-data buffer reset/replay cases')):
    path=ROOT/f'build/{variant}/{variant}.sim/sim_1/behav/xsim/simulate.log'
    text=path.read_text();assert marker in text and not re.search(r'Fatal:|ERROR:|cannot be opened for reading',text),variant
    paths.append(path)
paths += [ROOT/'rtl/experimental'/name for name in ('qn_branch512_ab_pw_core.v','qn_branch512_ab_inner.sv','qn_branch512_ab_axis.sv','qn_branch512_slice_pw_core.v')]
paths += [ROOT/'sim/qn_mac_ab_model.sv',ROOT/'sim/fast/qn_branch512_ab_pw_core.v',ROOT/'sim/tb_ab_mac_conformance.sv']
paths += [ROOT/f'sim/tb_qn_branch512_ab_{kind}.sv' for kind in ('axis','reset','payload_reset')]
paths += [ROOT/'scripts'/name for name in ('create_branch512_ab.py','create_ab_mac_conformance.py','ab_mac_conformance.tcl','branch512_ab_fast_sim.tcl','branch512_ab_reset_sim.tcl','branch512_ab_payload_reset_sim.tcl','bind_branch512_ab_regression.py','check_branch512_ab_software.py')]
paths += [ROOT/'reports/fused/branch512_guard_regression_evidence.json']
proof={'complete':True,'hardware_execution':False,'pointwise_macs':512,'depthwise_macs':64,
       'vendor_old_new_model_checks':203980,'exhaustive_signed_byte_products':65536,
       'random_control_cycles':6000,'independent_enable_reset_checks':True,'int32_overflow_checked':True,
       'mac_latency_cycles':2,'controller_and_arithmetic_unchanged':True,
       'sequential_equivalence_argument':'With coupled A/B enables and resets, the registered operand product follows the same recurrence as old MREG. The PREG recurrence and enable/reset are unchanged.',
       'full_blocks_checked':25,'full_reset_replay_cases':8,
       'sources_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
dest=ROOT/'reports/fused/branch512_ab_regression_evidence.json'
if dest.exists():assert json.loads(dest.read_text())==proof
else:dest.write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: exact MAC input retiming, 203980 vendor checks, 25 full blocks and eight reset/replay cases bound')
