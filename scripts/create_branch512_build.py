"""Isolated residual/bimodal candidate retaining the qualified 512-MAC datapath."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def save(path,text):
    path=ROOT/path
    if path.exists():assert path.read_text()==text,path
    else:path.write_text(text)
core=(ROOT/'rtl/experimental/qn_stream_pw_core.v').read_text()
core=core.replace('module qn_stream_pw_core','module qn_branch512_pw_core')
core=core.replace('input wire [4:0] cache_select,','input wire allow_wrap,input wire [4:0] cache_select,')
core=core.replace('fused_affine_quant_exact #','fused_affine_quant_select_wrap #')
assert core.count('.m_error(qerror));')==1
core=core.replace('.m_error(qerror));','.m_error(qerror),.s_wrap(allow_wrap));')
save(Path('rtl/experimental/qn_branch512_pw_core.v'),core)
save(Path('sim/fast/qn_branch512_pw_core.v'),core.replace('DSP48E2 #(','qn_mac_model #('))
inner=(ROOT/'rtl/experimental/qn_branch_bimodal_inner.sv').read_text()
inner=inner.replace('qn_branch_bimodal_inner','qn_branch512_inner').replace('qn_branch_pw_core','qn_branch512_pw_core')
save(Path('rtl/experimental/qn_branch512_inner.sv'),inner)
axis=(ROOT/'rtl/experimental/qn_branch_bimodal_axis.sv').read_text().replace('qn_branch_bimodal_inner','qn_branch512_inner')
save(Path('rtl/experimental/qn_branch512_axis.sv'),axis)
tb=(ROOT/'sim/tb_qn_branch_bimodal_axis.sv').read_text().replace('tb_qn_branch_bimodal_axis','tb_qn_branch512_axis').replace('nt*4*256','nt*8*256')
save(Path('sim/tb_qn_branch512_axis.sv'),tb)
sim=(ROOT/'scripts/branch_bimodal_fast_sim.tcl').read_text().replace('branch_bimodal_fast_sim','branch512_fast_sim')
sim=sim.replace('qn_branch_bimodal_axis','qn_branch512_axis').replace('qn_branch_bimodal_inner','qn_branch512_inner').replace('qn_branch_pw_core','qn_branch512_pw_core')
save(Path('scripts/branch512_fast_sim.tcl'),sim)
synth=(ROOT/'scripts/branch_bimodal_synth.tcl').read_text().replace('branch_bimodal','branch512').replace('qn_branch_pw_core','qn_branch512_pw_core')
synth=synth.replace('qn_branch512_bimodal','qn_branch512')
save(Path('scripts/branch512_synth.tcl'),synth)
print('Prepared isolated 512-MAC residual/bimodal RTL and 25-case regression; no physical qualification')
