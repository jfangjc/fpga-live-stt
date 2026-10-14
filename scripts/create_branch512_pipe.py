"""Separate raw-output selection from exact quantization with an elastic register."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def save(name,text):
    p=ROOT/name
    if p.exists():assert p.read_text()==text,p
    else:p.write_text(text)
core=(ROOT/'rtl/experimental/qn_branch512_pw_core.v').read_text().replace('qn_branch512_pw_core','qn_branch512_pipe_pw_core')
start=core.index(' fused_affine_quant_select_wrap #')
end=core.index('\n assign s_axis_tready',start)
old=core[start:end]
new=old.replace('.s_acc(qa),.s_bias(qb),.s_multiplier(qm),.s_shift(qs),.s_zero(qz)',
                '.s_acc(buffer_acc),.s_bias(buffer_bias),.s_multiplier(buffer_multiplier),.s_shift(buffer_shift),.s_zero(buffer_zero)')
new=new.replace('.s_valid(state==QUANT && quant_feed<16 && !error),.s_ready(qready)',
                '.s_valid(buffer_valid),.s_ready(quant_ready)').replace('.s_wrap(allow_wrap)', '.s_wrap(buffer_wrap)')
buffer=''' // Elastic input register splits the accumulation selector from quantization.
 reg [511:0] buffer_acc,buffer_bias,buffer_multiplier;
 reg [95:0] buffer_shift;reg [127:0] buffer_zero;
 reg buffer_valid,buffer_wrap;wire quant_ready;
 assign qready=!buffer_valid || quant_ready;
 always @(posedge aclk)begin
  if(!qreset)begin
   buffer_valid<=0;buffer_wrap<=0;buffer_acc<=0;buffer_bias<=0;
   buffer_multiplier<=0;buffer_shift<=0;buffer_zero<=0;
  end else if(qready)begin
   buffer_valid<=quant_feed<16;
   if(quant_feed<16)begin
    buffer_acc<=qa;buffer_bias<=qb;buffer_multiplier<=qm;
    buffer_shift<=qs;buffer_zero<=qz;buffer_wrap<=allow_wrap;
   end
  end
 end
'''
core=core[:start]+buffer+new+core[end:]
save(Path('rtl/experimental/qn_branch512_pipe_pw_core.v'),core)
save(Path('sim/fast/qn_branch512_pipe_pw_core.v'),core.replace('DSP48E2 #(','qn_mac_model #('))
inner=(ROOT/'rtl/experimental/qn_branch512_inner.sv').read_text().replace('qn_branch512_inner','qn_branch512_pipe_inner').replace('qn_branch512_pw_core','qn_branch512_pipe_pw_core')
save(Path('rtl/experimental/qn_branch512_pipe_inner.sv'),inner)
axis=(ROOT/'rtl/experimental/qn_branch512_axis.sv').read_text().replace('qn_branch512_inner','qn_branch512_pipe_inner')
save(Path('rtl/experimental/qn_branch512_pipe_axis.sv'),axis)
tb=(ROOT/'sim/tb_qn_branch512_axis.sv').read_text().replace('tb_qn_branch512_axis','tb_qn_branch512_pipe_axis')
save(Path('sim/tb_qn_branch512_pipe_axis.sv'),tb)
sim=(ROOT/'scripts/branch512_fast_sim.tcl').read_text().replace('branch512','branch512_pipe')
save(Path('scripts/branch512_pipe_fast_sim.tcl'),sim)
print('Prepared isolated elastic quantizer input pipeline; timing and full RTL regression pending')
