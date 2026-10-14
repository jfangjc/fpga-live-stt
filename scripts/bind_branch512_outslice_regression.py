"""Bind unchanged arithmetic and the registered stream-boundary regressions."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
exec((ROOT/'scripts/check_branch512_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_branch512_software.py')})
paths=[]
for variant,marker in (('branch512_outslice_fast','PASS: 25 two-output residual branches'),
                       ('branch512_outslice_reset','PASS: 6 full-pipeline reset/replay cases'),
                       ('branch512_outslice_payload_reset','PASS: 2 full output-data buffer reset/replay cases'),
                       ('voice_inference','PASS: 77 AXI accesses')):
    p=ROOT/f'build/{variant}_sim/{variant}_sim.sim/sim_1/behav/xsim/simulate.log'
    text=p.read_text();assert marker in text and not re.search(r'Fatal:|ERROR:|cannot be opened for reading',text)
    paths.append(p)
real=ROOT/'rtl/experimental/qn_branch512_slice_pw_core.v'
assert real.read_text()==(ROOT/'rtl/experimental/qn_branch512_pipe_pw_core.v').read_text().replace('qn_branch512_pipe_pw_core','qn_branch512_slice_pw_core')
assert real.read_text().replace('DSP48E2 #(','qn_mac_model #(')==(ROOT/'sim/fast/qn_branch512_slice_pw_core.v').read_text()
paths += [ROOT/'rtl/experimental'/n for n in ('qn_branch512_outslice_axis.sv','qn_branch512_slice_inner.sv','qn_branch512_slice_pw_core.v','voice_axi_inference.v')]
paths += [ROOT/'sim'/n for n in ('tb_qn_branch512_outslice_axis.sv','tb_qn_branch512_outslice_reset.sv','tb_voice_inference.sv','fast/qn_branch512_slice_pw_core.v')]
paths += [ROOT/'scripts'/n for n in ('create_branch512_outslice.py','create_branch512_outslice_tools.py','branch512_outslice_fast_sim.tcl','branch512_outslice_reset_sim.tcl','voice_inference_sim.tcl','bind_branch512_outslice_regression.py')]
paths += [ROOT/'sim/tb_qn_branch512_outslice_payload_reset.sv',ROOT/'scripts/create_branch512_outslice_payload_reset.py',ROOT/'scripts/branch512_outslice_payload_reset_sim.tcl']
paths += [ROOT/'rtl/sph0645_rx.v',ROOT/'reports/fused/branch512_regression_evidence.json']
proof={'complete':True,'hardware_execution':False,'pointwise_macs':512,'depthwise_macs':64,
       'pipelined_cases':25,'full_pipeline_reset_replay_cases':6,'voice_axi_accesses':77,'output_data_reset_replay_cases':2,
       'legacy_mac_disabled':True,'capture_qualified':False,'arithmetic_unchanged':True,
       'simulation_substitution':'Vendor-conformant simulation MAC; actual controllers, XPM and exact quantizers',
       'sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}}
(ROOT/'reports/fused/branch512_outslice_regression_evidence.json').write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: 25 full blocks, six output/stream/quantizer resets, 77 AXI accesses and unchanged arithmetic bound')
