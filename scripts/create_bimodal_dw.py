"""Extend retained DW scheduling to two channels at 17..32 time steps."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def write(name,text):
    path=ROOT/name
    if path.exists():assert path.read_text()==text,str(path)
    else:path.write_bytes(text.encode())
text=(ROOT/'rtl/experimental/fused_depthwise_quad.sv').read_text()
text=text.replace('fused_depthwise_quad','fused_depthwise_bimodal')
text=text.replace(' reg short_mode;', ' reg short_mode;\n wire quad_mode=short_mode && times<=16;\n wire dual_mode=short_mode && times>16;')
text=text.replace('quant_channel=short_mode?quant_sent[1:0]:2\'d0;',
                  "quant_channel=quad_mode?quant_sent[1:0]:dual_mode?{1'b0,quant_sent[1]}:2'd0;")
text=text.replace('(cfg_times<=16 || b==0)', '(cfg_times<=16 || (cfg_times<=32 && b<2) || b==0)')
text=text.replace('(short_mode?(b%16):b)', '(quad_mode?(b%16):dual_mode?(b%32):b)')
text=text.replace('(short_mode?(b/16):0)', '(quad_mode?(b/16):dual_mode?(b/32):0)')
text=text.replace('(short_mode?(i%16):i)', '(quad_mode?(i%16):dual_mode?(i%32):i)')
text=text.replace('(short_mode?(i/16):0)', '(quad_mode?(i/16):dual_mode?(i/32):0)')
text=text.replace('short_mode<=cfg_times<=16;', 'short_mode<=cfg_times<=32;')
assert 'dual_mode' in text and 'short_mode<=cfg_times<=32' in text
write('rtl/experimental/fused_depthwise_bimodal.sv',text)
text=(ROOT/'rtl/experimental/qn_quad_inner.sv').read_text().replace('qn_quad_inner','qn_bimodal_inner').replace('fused_depthwise_quad','fused_depthwise_bimodal')
text=text.replace('short_mode=times<=16;', 'short_mode=times<=32;')
text=text.replace("channel_step=short_mode?10'd4:10'd1;", "channel_step=times<=16?10'd4:times<=32?10'd2:10'd1;")
text=text.replace('fetch_channel==3)', 'fetch_channel==channel_step-1)')
write('rtl/experimental/qn_bimodal_inner.sv',text)
text=(ROOT/'rtl/experimental/qn_quad_axis.sv').read_text().replace('qn_quad_inner','qn_bimodal_inner')
write('rtl/experimental/qn_bimodal_axis.sv',text)
text=(ROOT/'scripts/create_adaptive_dw_tb.py').read_text()
text=text.replace('verification/adaptive-dw','verification/bimodal-dw')
text=text.replace('(1,7,13,16,17,51,65,101,256)', '(1,7,13,16,17,31,32,33,51,65,101,256)')
text=text.replace('channels=4 if t<=16 else 1', 'channels=4 if t<=16 else 2 if t<=32 else 1')
text=text.replace('beats=1 if channels==4 else', 'beats=1 if channels>1 else')
text=text.replace('c=b//16 if channels==4 else 0;p=b%16 if channels==4 else tile*64+b',
                  'c=b//(64//channels) if channels>1 else 0;p=b%(64//channels) if channels>1 else tile*64+b')
text=text.replace('tb_adaptive_dw','tb_bimodal_dw').replace('fused_depthwise_adaptive','fused_depthwise_bimodal')
text=text.replace('configs[0:134]','configs[0:179]').replace('metadata[0:134]','metadata[0:179]').replace('i<135','i<180')
text=text.replace('adaptive DW float32 cases','bimodal DW float32 cases').replace('16/17 boundary','16/17 and 32/33 boundaries')
write('scripts/create_bimodal_dw_tb.py',text)
text=(ROOT/'scripts/adaptive_dw_sim.tcl').read_text().replace('adaptive_dw_sim','bimodal_dw_sim').replace('tb_adaptive_dw','tb_bimodal_dw')
text=text.replace('fused_depthwise_adaptive','fused_depthwise_bimodal').replace('fused_affine_quant_exact','fused_affine_quant_compact')
text=text.replace('PASS: 135 adaptive DW','PASS: 180 bimodal DW')
write('scripts/bimodal_dw_sim.tcl',text)
print('Prepared isolated two/four-channel DW unit and 180-case fixture generator')
