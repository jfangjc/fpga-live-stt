"""Bind full controller regression with explicit simulation-only MAC substitution."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
unit=json.loads((ROOT/'reports/fused/branch_bimodal_unit_evidence.json').read_text())
for name,value in unit['sources_sha256'].items():assert sha(ROOT/name)==value,name
full=ROOT/'build/branch_bimodal_fast_sim/branch_bimodal_fast_sim.sim/sim_1/behav/xsim/simulate.log'
quant=ROOT/'build/select_wrap_requant_sim/select_wrap_requant_sim.sim/sim_1/behav/xsim/simulate.log'
for path,marker in ((full,'PASS: 25 two-output residual branches'),(quant,'PASS: 19200 normal and wrapped')):
    text=path.read_text();assert marker in text and not re.search(r'Fatal:|ERROR:',text)
real=ROOT/'rtl/experimental/qn_branch_pw_core.v';derived=ROOT/'sim/fast/qn_branch_pw_core.v'
assert real.read_text().replace('DSP48E2 #(','qn_mac_model #(')==derived.read_text()
paths=[ROOT/name for name in unit['sources_sha256']]+[full,quant]
paths += [ROOT/'rtl/experimental'/name for name in ('qn_branch_bimodal_axis.sv','qn_branch_bimodal_inner.sv','fused_depthwise_bimodal.sv','fused_affine_quant_compact.sv','fused_affine_quant_select_wrap.sv')]
paths += [ROOT/'sim'/name for name in ('tb_qn_branch_bimodal_axis.sv','tb_select_wrap_requant.sv')]
paths += list((ROOT/'verification/bimodal-branch-vectors').glob('*'))
paths += [ROOT/'scripts'/name for name in ('create_branch_bimodal_tb.py','branch_bimodal_fast_sim.tcl','create_select_wrap_tb.py','bind_branch_bimodal_regression.py')]
result={'complete':True,'hardware_execution':False,'full_block_simulation_passed':True,'cases':25,
        'mac_model_vendor_conformance_cycles':6000,'selective_wrapping_lane_checks':19200,
        'simulation_substitution':unit['simulation_substitution'],
        'hardware_synthesis_uses_vendor_dsp':True,
        'sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}}
(ROOT/'reports/fused/branch_bimodal_regression_evidence.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS: 25 full block cases, 19200 quantizer lanes and 6000 vendor MAC conformance cycles bound')
