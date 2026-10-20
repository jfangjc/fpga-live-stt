"""Prepare protocol-18 shared-input residual RTL after exact software gates."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=json.loads((ROOT/'reports/fused/branch_transport_oracle.json').read_text())
assert p['complete'] and p['all_cpu_logits_bit_exact'] and len(p['clips'])==36
assert p['total_pairs']==121 and not p['physical_branch_implemented']
for key,name in (('library_sha256','software/ort_fpga_stream_branch/libort_fpga.so'),
                 ('runtime_source_sha256','software/ort_fpga_stream_branch/pointwise.cc'),
                 ('compiler_sha256','software/ort_fpga_stream_branch/branch_graph.py'),
                 ('source_sha256','software/latency/validate_branch_oracle.py')):
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==p[key],name
log=(ROOT/'build/select_wrap_requant_sim/select_wrap_requant_sim.sim/sim_1/behav/xsim/simulate.log').read_text()
assert 'PASS: 19200 normal and wrapped float32-equivalent lanes' in log
assert not re.search(r'Fatal:|ERROR:',log)
def write(name,text):
    path=ROOT/name
    if path.exists():assert path.read_text()==text,str(path)
    else:path.write_bytes(text.encode())
text=(ROOT/'rtl/experimental/qn_quad_pw_core.v').read_text()
text=text.replace('qn_quad_pw_core','qn_branch_pw_core').replace('fused_affine_quant_compact','fused_affine_quant_select_wrap')
text=text.replace('input wire [4:0] cache_select,','input wire allow_wrap,input wire [4:0] cache_select,')
text=text.replace('.m_error(qerror));','.m_error(qerror),.s_wrap(allow_wrap));')
write('rtl/experimental/qn_branch_pw_core.v',text)
text=(ROOT/'rtl/experimental/qn_quad_inner.sv').read_text().replace('qn_quad_inner','qn_branch_inner').replace('qn_quad_pw_core','qn_branch_pw_core')
text=text.replace(' output wire busy,output reg done,output wire error',' input wire allow_wrap,output wire busy,output reg done,output wire error')
assert '.cache_select(core_slot)' in text
text=text.replace('.cache_select(core_slot)', '.allow_wrap(allow_wrap),.cache_select(core_slot)')
write('rtl/experimental/qn_branch_inner.sv',text)
text=(ROOT/'rtl/experimental/qn_quad_axis.sv').read_text().replace('qn_quad_inner','qn_branch_inner')
text=text.replace(' reg bad;', ' reg bad,branch_mode;\n wire branch_step=branch_mode && step==0;\n wire emit_step=final_step || branch_step;')
text=text.replace('final_step?m_axis_tready','emit_step?m_axis_tready')
text=text.replace('&& final_step && inner_valid','&& emit_step && inner_valid')
text=text.replace('state==ACK && final_step?', 'state==ACK && emit_step?')
text=text.replace('state<=IDLE;done<=0;bad<=0;', 'state<=IDLE;done<=0;bad<=0;branch_mode<=0;')
text=text.replace('outer_tag<=s_axis_tdata[127:96];times<=','branch_mode<=s_axis_tdata[39:32]==18;outer_tag<=s_axis_tdata[127:96];times<=')
text=text.replace('s_axis_tdata[39:32]!=17 ||','(s_axis_tdata[39:32]!=17 && s_axis_tdata[39:32]!=18) ||')
text=text.replace('s_axis_tdata[23:16]==0 || s_axis_tdata[23:16]>8)',
                  's_axis_tdata[23:16]==0 || s_axis_tdata[23:16]>8 || (branch_mode && s_axis_tdata[23:16]<2))')
text=text.replace('state<=count==1?RUNHEAD:LUTREAD;', 'state<=(count==1 || branch_mode)?RUNHEAD:LUTREAD;')
text=text.replace('         if(final_step)begin\n           if(time_row==15)', '         if(emit_step)begin\n           if(time_row==15)')
text=text.replace('.aclk(aclk),.aresetn(aresetn),.s_axis_tdata(inner_input_data)',
                  '.aclk(aclk),.aresetn(aresetn),.allow_wrap(branch_step),.s_axis_tdata(inner_input_data)')
assert 'if(emit_step)begin' in text and '.allow_wrap(branch_step)' in text
text='// Protocol 18 emits residual stage zero, preserves original input, then emits the final main stage.\n'+text
write('rtl/experimental/qn_branch_axis.sv',text)
print('Prepared isolated two-output branch RTL; full protocol regression and physical transport are pending')
