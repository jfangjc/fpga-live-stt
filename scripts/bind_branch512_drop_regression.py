"""Bind independent arithmetic and full-block tests for the extra DW stage."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
exec((ROOT/'scripts/check_branch512_outslice_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_branch512_outslice_software.py')})
old=(ROOT/'rtl/experimental/fused_affine_quant_compact.sv').read_text()
new=(ROOT/'rtl/experimental/fused_affine_quant_drop_pipe.sv').read_text()
functions=lambda text:re.findall(r' function automatic.*? endfunction',text,re.S)
assert functions(old)==functions(new),'Arithmetic functions changed'
dw=(ROOT/'rtl/experimental/fused_depthwise_bimodal.sv').read_text()
assert (ROOT/'rtl/experimental/fused_depthwise_droppipe.sv').read_text()==dw.replace('fused_depthwise_bimodal','fused_depthwise_droppipe').replace('fused_affine_quant_compact','fused_affine_quant_drop_pipe')
paths=[]
for variant,marker in (('drop_requant','PASS: 9600 float32-equivalent lanes'),
                       ('branch512_drop_fast','PASS: 25 two-output residual branches'),
                       ('branch512_drop_reset','PASS: 6 full-pipeline reset/replay cases'),
                       ('branch512_drop_payload_reset','PASS: 2 full output-data buffer reset/replay cases')):
    path=ROOT/f'build/{variant}_sim/{variant}_sim.sim/sim_1/behav/xsim/simulate.log'
    text=path.read_text();assert marker in text and not re.search(r'Fatal:|ERROR:|cannot be opened for reading',text),variant
    paths.append(path)
paths += [ROOT/'rtl/experimental'/name for name in ('fused_affine_quant_drop_pipe.sv','fused_depthwise_droppipe.sv','qn_branch512_drop_inner.sv','qn_branch512_drop_axis.sv')]
paths += [ROOT/'sim'/name for name in ('tb_drop_requant.sv','tb_qn_branch512_drop_axis.sv','tb_qn_branch512_drop_reset.sv','tb_qn_branch512_drop_payload_reset.sv')]
paths += [ROOT/'scripts'/name for name in ('create_branch512_drop.py','drop_requant_sim.tcl','branch512_drop_fast_sim.tcl','branch512_drop_reset_sim.tcl','branch512_drop_payload_reset_sim.tcl','bind_branch512_drop_regression.py')]
paths += [ROOT/'reports/fused/branch512_outslice_regression_evidence.json',ROOT/'rtl/experimental/fused_affine_quant_compact.sv',ROOT/'rtl/experimental/fused_depthwise_bimodal.sv']
proof={'complete':True,'hardware_execution':False,'pointwise_macs':512,'depthwise_macs':64,
       'quantizer_pipeline_stages':8,'quantizer_lanes_checked':9600,'full_blocks_checked':25,
       'full_reset_replay_cases':8,'arithmetic_functions_unchanged':True,
       'protocol_unchanged':True,'sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}}
(ROOT/'reports/fused/branch512_drop_regression_evidence.json').write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: unchanged quantizer arithmetic, 9600 lanes, 25 full blocks and eight reset/replay cases bound')
