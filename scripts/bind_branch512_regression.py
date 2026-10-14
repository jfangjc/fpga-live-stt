"""Bind both 512-MAC block regressions and full elastic pipeline reset coverage."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];reports=ROOT/'reports/fused'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
parent=json.loads((reports/'branch_bimodal_unit_evidence.json').read_text())
for name,value in parent['sources_sha256'].items():assert sha(ROOT/name)==value,name
paths=[ROOT/name for name in parent['sources_sha256']]
for variant,marker in (('branch512_fast','PASS: 25 two-output residual branches'),
                       ('branch512_pipe_fast','PASS: 25 two-output residual branches'),
                       ('branch512_pipe_reset','PASS: 2 full-pipeline reset/replay cases')):
    path=ROOT/f'build/{variant}_sim/{variant}_sim.sim/sim_1/behav/xsim/simulate.log'
    text=path.read_text();assert marker in text and not re.search(r'Fatal:|ERROR:|cannot be opened for reading',text)
    paths.append(path)
def primitive(path):
    text=path.read_text();a=text.index('DSP48E2 #(');return text[a:text.index(');',a)+2]
real_parent=ROOT/'rtl/experimental/qn_branch_pw_core.v'
for variant in ('branch512','branch512_pipe'):
    real=ROOT/f'rtl/experimental/qn_{variant}_pw_core.v';derived=ROOT/f'sim/fast/qn_{variant}_pw_core.v'
    assert primitive(real)==primitive(real_parent)
    assert real.read_text().replace('DSP48E2 #(','qn_mac_model #(')==derived.read_text()
    paths += [real,derived,ROOT/f'rtl/experimental/qn_{variant}_axis.sv',ROOT/f'rtl/experimental/qn_{variant}_inner.sv',
              ROOT/f'sim/tb_qn_{variant}_axis.sv',ROOT/f'scripts/{variant}_fast_sim.tcl']
paths += list((ROOT/'verification/bimodal-branch-vectors').glob('*'))
paths += [ROOT/'rtl/experimental'/n for n in ('fused_depthwise_bimodal.sv','fused_affine_quant_compact.sv','fused_affine_quant_select_wrap.sv')]
paths += [ROOT/'scripts'/n for n in ('create_branch512_build.py','create_branch512_pipe.py','create_branch512_pipe_reset.py','branch512_pipe_reset_sim.tcl','bind_branch512_regression.py')]
paths += [ROOT/'sim/tb_qn_branch512_pipe_reset.sv']
proof={'complete':True,'hardware_execution':False,'pointwise_macs':512,'depthwise_macs':64,
       'unpipelined_cases':25,'pipelined_cases':25,'full_pipeline_reset_replay_cases':2,
       'mac_model_vendor_conformance_cycles':6000,'simulation_substitution':parent['simulation_substitution'],
       'sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}}
(reports/'branch512_regression_evidence.json').write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: two 25-case block regressions, full pipeline reset/replay and conformant vendor MAC configuration bound')
