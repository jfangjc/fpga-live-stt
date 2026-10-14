"""Preserve routed OUTSLICE166; split DW effective-drop and final rounding."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def save(name,text):
    path=ROOT/name
    if path.exists():assert path.read_text()==text,path
    else:path.write_text(text,newline='\n')

quant=(ROOT/'rtl/experimental/fused_affine_quant_compact.sv').read_text()
quant=quant.replace('fused_affine_quant_compact','fused_affine_quant_drop_pipe')
quant=quant.replace('reg [6:0] valid;wire [6:0] ready;', 'reg [7:0] valid;wire [7:0] ready;')
quant=quant.replace('assign ready[6]=!valid[6] || m_ready;', 'assign ready[7]=!valid[7] || m_ready;')
quant=quant.replace('g<6;', 'g<7;').replace('m_valid=aresetn && valid[6]', 'm_valid=aresetn && valid[7]')
quant=quant.replace('shifts[0:5]','shifts[0:6]').replace('zeros[0:5]','zeros[0:6]').replace('negative[0:5],invalid[0:5]', 'negative[0:6],invalid[0:6]')
quant=quant.replace('integer i,j;reg signed', '''// Separate the shift arithmetic from the barrel shift / rounding / zero add.
 reg signed [7:0] round_drop[0:LANES-1];reg [23:0] round_mant[0:LANES-1];
 integer i,j;reg signed''')
quant=quant.replace('j<6;', 'j<7;')
quant=quant.replace('if(ready[6])begin\n    valid[6]<=valid[5];\n    if(valid[5])begin\n     m_error<=|invalid[5];', 'if(ready[7])begin\n    valid[7]<=valid[6];\n    if(valid[6])begin\n     m_error<=|invalid[6];')
quant=quant.replace('m_data[i*8+:8]<=invalid[5][i]', 'm_data[i*8+:8]<=invalid[6][i]')
old='''   if(ready[5] && valid[4])for(i=0;i<LANES;i=i+1)begin
    effective_drop=$signed({2'b0,shifts[4][i]})-$signed({4'b0,a_drop[4][i]})-8'sd7-$signed({2'b0,p_drop_rounded[i]});
    integer_result[i]<=final_integer(p_mant[i],effective_drop,negative[4][i],zeros[4][i]);
   end'''
new='''   if(ready[6] && valid[5])for(i=0;i<LANES;i=i+1)begin
    integer_result[i]<=final_integer(round_mant[i],round_drop[i],negative[5][i],zeros[5][i]);
   end
   if(ready[5] && valid[4])for(i=0;i<LANES;i=i+1)begin
    effective_drop=$signed({2'b0,shifts[4][i]})-$signed({4'b0,a_drop[4][i]})-8'sd7-$signed({2'b0,p_drop_rounded[i]});
    round_drop[i]<=effective_drop;round_mant[i]<=p_mant[i];
   end'''
assert old in quant;quant=quant.replace(old,new)
save('rtl/experimental/fused_affine_quant_drop_pipe.sv',quant)
dw=(ROOT/'rtl/experimental/fused_depthwise_bimodal.sv').read_text().replace('fused_depthwise_bimodal','fused_depthwise_droppipe').replace('fused_affine_quant_compact','fused_affine_quant_drop_pipe')
save('rtl/experimental/fused_depthwise_droppipe.sv',dw)
inner=(ROOT/'rtl/experimental/qn_branch512_slice_inner.sv').read_text().replace('qn_branch512_slice_inner','qn_branch512_drop_inner').replace('fused_depthwise_bimodal','fused_depthwise_droppipe')
save('rtl/experimental/qn_branch512_drop_inner.sv',inner)
axis=(ROOT/'rtl/experimental/qn_branch512_outslice_axis.sv').read_text().replace('qn_branch512_slice_inner','qn_branch512_drop_inner')
save('rtl/experimental/qn_branch512_drop_axis.sv',axis)
for kind in ('axis','reset','payload_reset'):
    tb=(ROOT/f'sim/tb_qn_branch512_outslice_{kind}.sv').read_text().replace(f'tb_qn_branch512_outslice_{kind}',f'tb_qn_branch512_drop_{kind}')
    save(f'sim/tb_qn_branch512_drop_{kind}.sv',tb)
    variant='fast' if kind=='axis' else kind
    tcl=(ROOT/f'scripts/branch512_outslice_{variant}_sim.tcl').read_text()
    tcl=tcl.replace('branch512_outslice','branch512_drop').replace('qn_branch512_slice_inner','qn_branch512_drop_inner').replace('fused_depthwise_bimodal','fused_depthwise_droppipe').replace('fused_affine_quant_compact','fused_affine_quant_drop_pipe')
    save(f'scripts/branch512_drop_{variant}_sim.tcl',tcl)
tb=(ROOT/'sim/tb_compact_requant.sv').read_text().replace('tb_compact_requant','tb_drop_requant').replace('fused_affine_quant_compact','fused_affine_quant_drop_pipe')
save('sim/tb_drop_requant.sv',tb)
tcl=(ROOT/'scripts/compact_requant_sim.tcl').read_text().replace('compact_requant','drop_requant').replace('fused_affine_quant_compact','fused_affine_quant_drop_pipe')
save('scripts/drop_requant_sim.tcl',tcl)
print('Prepared isolated eight-stage DW quantizer; all arithmetic functions unchanged')
