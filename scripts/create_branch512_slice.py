"""Preserve PIPE166; isolate an elastic DW/PW boundary and inference-only voice."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def save(name,text):
    path=ROOT/name
    if path.exists():assert path.read_text()==text,path
    else:path.write_text(text)

core=(ROOT/'rtl/experimental/qn_branch512_pipe_pw_core.v').read_text().replace('qn_branch512_pipe_pw_core','qn_branch512_slice_pw_core')
save('rtl/experimental/qn_branch512_slice_pw_core.v',core)
save('sim/fast/qn_branch512_slice_pw_core.v',core.replace('DSP48E2 #(','qn_mac_model #('))
inner=(ROOT/'rtl/experimental/qn_branch512_pipe_inner.sv').read_text().replace('qn_branch512_pipe_inner','qn_branch512_slice_inner').replace('qn_branch512_pipe_pw_core','qn_branch512_slice_pw_core')
start=inner.index(' qn_branch512_slice_pw_core #')
end=inner.index(' fused_depthwise_bimodal #',start)
instance=inner[start:end]
instance=instance.replace('.s_axis_tdata(cs_data),.s_axis_tvalid(cs_valid),.s_axis_tready(cs_ready),.s_axis_tlast(cs_last)',
    '.s_axis_tdata(slice_data),.s_axis_tvalid(slice_valid),.s_axis_tready(slice_ready),.s_axis_tlast(slice_last)')
register=''' // Elastic stream register prevents DW data/masks reaching header validation.
 reg [127:0] slice_data;reg slice_valid,slice_last;wire slice_ready;
 assign cs_ready=!slice_valid || slice_ready;
 always @(posedge aclk)begin
  if(!aresetn)begin slice_data<=0;slice_valid<=0;slice_last<=0;end
  else if(cs_ready)begin
   slice_valid<=cs_valid;
   if(cs_valid)begin slice_data<=cs_data;slice_last<=cs_last;end
  end
 end
'''
inner=inner[:start]+register+instance+inner[end:]
save('rtl/experimental/qn_branch512_slice_inner.sv',inner)
axis=(ROOT/'rtl/experimental/qn_branch512_pipe_axis.sv').read_text().replace('qn_branch512_pipe_inner','qn_branch512_slice_inner')
save('rtl/experimental/qn_branch512_slice_axis.sv',axis)
tb=(ROOT/'sim/tb_qn_branch512_pipe_axis.sv').read_text().replace('tb_qn_branch512_pipe_axis','tb_qn_branch512_slice_axis')
save('sim/tb_qn_branch512_slice_axis.sv',tb)
sim=(ROOT/'scripts/branch512_pipe_fast_sim.tcl').read_text().replace('branch512_pipe','branch512_slice')
save('scripts/branch512_slice_fast_sim.tcl',sim)
reset=(ROOT/'sim/tb_qn_branch512_pipe_reset.sv').read_text().replace('tb_qn_branch512_pipe_reset','tb_qn_branch512_slice_reset')
reset_namespace={'__file__':str(ROOT/'scripts/create_branch512_slice_reset.py'),'__name__':'generator_helper'}
exec((ROOT/'scripts/create_branch512_slice_reset.py').read_text(),reset_namespace)
reset=reset_namespace['expand_reset'](reset)
save('sim/tb_qn_branch512_slice_reset.sv',reset)
reset_sim=(ROOT/'scripts/branch512_pipe_reset_sim.tcl').read_text().replace('branch512_pipe','branch512_slice')
reset_sim=reset_sim.replace('PASS: 2 full-pipeline reset/replay cases','PASS: 4 full-pipeline reset/replay cases')
save('scripts/branch512_slice_reset_sim.tcl',reset_sim)

voice=(ROOT/'rtl/experimental/voice_axi_auto_clock.v').read_text()
a=voice.index('    qn_mac mac(');b=voice.index('    wire [23:0] sample;',a)
voice=voice[:a]+'    // Legacy MAC is absent in this separate inference image.\n    assign mac_read = 32\'b0;\n'+voice[b:]
voice=voice.replace("wire write_ok = awaddr[1:0] == 0 && !awaddr[15] && wstrb == 4'hf;","wire write_ok = 1'b0; // No writable capture registers; legacy MAC disabled.")
voice=voice.replace('else if (!s_axi_araddr[15]) s_axi_rdata <= mac_read;',"else if (!s_axi_araddr[15]) begin s_axi_rdata <= 0; s_axi_rresp <= 2'b10; end")
voice=voice.replace('// AXI4-Lite, 100 MHz. Low 32 KB maps qn_mac; high half maps audio.',
    '// Inference experiment: legacy MAC addresses return SLVERR. Audio is unqualified at the new clock.')
save('rtl/experimental/voice_axi_inference.v',voice)
print('Prepared isolated stream boundary and legacy-MAC-free voice slave; regressions pending')
