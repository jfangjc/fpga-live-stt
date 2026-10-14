"""Isolate a streamed, eight-stage 256-channel block over the existing MAC core."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def write(name,text):
    p=ROOT/name
    if not p.exists() or p.read_text()!=text:p.write_bytes(text.encode())

pw=(ROOT/'rtl/experimental/qn_short_cache_core.v').read_text()
pw=pw.replace('module qn_short_cache_core','module qn_stream_pw_core')
pw=pw.replace('reg [31:0] slot_valid,slot_quant;','reg [7:0] slot_valid,slot_quant;')
pw=pw.replace('[0:31]','[0:7]').replace('reset_slot<32','reset_slot<8')
pw=pw.replace('32*((MAX_M+15)/16)','8*((MAX_M+15)/16)')
pw=pw.replace('KW+GW+4','KW+GW+2').replace('KW+GW+5','KW+GW+3')
pw=pw.replace('{cache_select,','{cache_select[2:0],')
pw=pw.replace("s_axis_tdata[47:40]!=0 ||", "s_axis_tdata[47:40]!=0 || cache_select>=8 ||")
pw=pw.replace('fused_affine_quant #','fused_affine_quant_exact #')
pw=pw.replace('s_axis_tdata[63] ||', 's_axis_tdata[63] || |s_axis_tdata[38:32] ||')
write('rtl/experimental/qn_stream_pw_core.v',pw)

dw=(ROOT/'rtl/experimental/fused_depthwise_channel_wide.sv').read_text()
dw=dw.replace('module fused_depthwise_channel_wide','module fused_depthwise_stream')
dw=dw.replace('MAX_KERNEL=21','MAX_KERNEL=41').replace('fused_affine_quant #','fused_affine_quant_exact #')
# Keep all 64 MAC time lanes, but share 16 exact requantizers over only the
# output quarters that the real time length needs. The inner engine already
# serializes this wide beat into 128-bit pieces.
dw=dw.replace('product_last,quant_sent;', 'product_last;\n reg [2:0] quant_sent,quant_received;reg quant_done;reg [LANES*8-1:0] quant_buffer;\n wire [12:0] remaining_times=times-time_tile*LANES;\n wire [2:0] quant_chunks=remaining_times>=LANES?4:(remaining_times+15)>>4;')
dw=dw.replace('wire [LANES*32-1:0] qa,qb,qm;', 'wire [16*32-1:0] qa,qb,qm;')
dw=dw.replace('wire [LANES*6-1:0] qs;', 'wire [16*6-1:0] qs;')
dw=dw.replace('wire [LANES*8-1:0] qz,qdata;', 'wire [16*8-1:0] qz,qdata;')
dw=dw.replace('state==QUANT && qvalid;', 'state==QUANT && quant_done;')
dw=dw.replace('  assign qa[b*32+:32]=accum[b];assign qb[b*32+:32]=bias;\n  assign qm[b*32+:32]=multiplier;assign qs[b*6+:6]=shift;assign qz[b*8+:8]=yzero;\n','')
dw=dw.replace('qdata[b*8+:8]:yzero;', 'quant_buffer[b*8+:8]:yzero;')
dw=dw.replace(' fused_affine_quant_exact #(.LANES(LANES)) quant(', ''' generate for(b=0;b<16;b=b+1)begin: quant_lanes
  assign qa[b*32+:32]=accum[quant_sent[1:0]*16+b];assign qb[b*32+:32]=bias;
  assign qm[b*32+:32]=multiplier;assign qs[b*6+:6]=shift;assign qz[b*8+:8]=yzero;
 end endgenerate
 fused_affine_quant_exact #(.LANES(16)) quant(''')
dw=dw.replace('.s_valid(state==QUANT && !quant_sent)', '.s_valid(state==QUANT && quant_sent<quant_chunks)')
dw=dw.replace('.m_ready(m_ready && state==QUANT)', '.m_ready(state==QUANT && !quant_done)')
dw=dw.replace('product_last<=0;quant_sent<=0;', 'product_last<=0;quant_sent<=0;quant_received<=0;quant_done<=0;quant_buffer<=0;')
dw=dw.replace('cfg_multiplier[31] ||', 'cfg_multiplier[31] || |cfg_multiplier[6:0] ||')
dw=dw.replace('product_valid<=0;quant_sent<=0;state<=MAC;', 'product_valid<=0;quant_sent<=0;quant_received<=0;quant_done<=0;quant_buffer<=0;state<=MAC;')
dw=dw.replace('     if(!quant_sent && qready)quant_sent<=1;\n     if(qvalid && m_ready)begin\n      if(qerror)error<=1;', '''     if(quant_sent<quant_chunks && qready)quant_sent<=quant_sent+1;
     if(qvalid && !quant_done)begin
      quant_buffer[quant_received[1:0]*128+:128]<=qdata;quant_received<=quant_received+1;
      if(qerror)error<=1;
      if(quant_received==quant_chunks-1)quant_done<=1;
     end
     if(quant_done && m_ready)begin''')
assert 'if(!quant_sent' not in dw and '.LANES(16)' in dw
write('rtl/experimental/fused_depthwise_stream.sv',dw)

inner=(ROOT/'rtl/experimental/qn_chain_inner.sv').read_text()
inner=inner.replace('module qn_short_wide_inner','module qn_stream_inner')
inner=inner.replace('reg [31:0] slot_dw_valid;', 'reg [7:0] slot_dw_valid;')
inner=inner.replace('[0:31]','[0:7]').replace('reset_slot<32','reset_slot<8').replace('r<32','r<8')
inner=inner.replace('reg [4:0] slot_kernel','reg [5:0] slot_kernel').replace('reg [4:0] kernel;', 'reg [5:0] kernel;')
inner=inner.replace('reg weight_half;reg [127:0] weight_low;', 'reg [1:0] weight_part;reg [255:0] weight_low;')
inner=inner.replace('hm>=11 && hm<=21','hm>=1 && hm<=41')
inner=inner.replace('s_axis_tdata[47:45]==0','s_axis_tdata[47:43]==0')
inner=inner.replace('reg [167:0] dw_weights[0:8191]','reg [327:0] dw_weights[0:2047]')
inner=inner.replace('reg [109:0] dw_params[0:8191]','reg [85:0] dw_params[0:2047]')
inner=inner.replace('reg [109:0] params;reg [167:0] current_weights;','reg [85:0] params;reg [327:0] current_weights;')
inner=inner.replace('{slot,channel[7:0]}','{slot[2:0],channel[7:0]}')
inner=inner.replace('qn_short_cache_core #','qn_stream_pw_core #')
inner=inner.replace('fused_depthwise_channel_wide #','fused_depthwise_stream #').replace('.MAX_KERNEL(21)','.MAX_KERNEL(41)')
inner=inner.replace("{2'b0,slot_kernel[slot]}","{1'b0,slot_kernel[slot]}").replace('params[109:102]','params[85:78]')
inner=inner.replace('weight_half','weight_part').replace('kernel<=hm[4:0]','kernel<=hm[5:0]')
start=inner.index('    DWWEIGHTS:if(accept)begin');end=inner.index('    DWPARAMS:',start)
inner=inner[:start]+'''    DWWEIGHTS:if(accept)begin
     if(weight_part!=2)begin
      weight_low[weight_part*128+:128]<=s_axis_tdata;weight_part<=weight_part+1;
     end else begin
      dw_weights[{slot[2:0],channel[7:0]}]<={s_axis_tdata[71:0],weight_low};weight_part<=0;
      if(channel==channels-1)begin channel<=0;state<=DWPARAMS;end
      else channel<=channel+1;
     end
     for(integer b=0;b<16;b=b+1)if(b+weight_part*16>=kernel && s_axis_tdata[b*8+:8]!=0)
       begin status<=2;local_error<=1;state<=s_axis_tlast?ACK:DRAIN;end
     if(s_axis_tlast)begin status<=2;local_error<=1;state<=ACK;end
    end
'''+inner[end:]
inner=inner.replace('s_axis_tdata[127:40]!=0','s_axis_tdata[127:72]!=0')
inner=inner.replace('{s_axis_tdata[39:0],weight_low}','{s_axis_tdata[71:0],weight_low}')
inner=inner.replace("{s_axis_tdata[103:96],24'b0,s_axis_tdata[79:72]", "{s_axis_tdata[103:96],s_axis_tdata[79:72]")
inner=inner.replace('s_axis_tdata[63] ||', 's_axis_tdata[63] || |s_axis_tdata[38:32] ||')
assert 'weight_part!=2' in inner and 'weight_half' not in inner and '24\'b0' not in inner
write('rtl/experimental/qn_stream_inner.sv',inner)

top=(ROOT/'rtl/experimental/qn_chain_prefetch_axis.sv').read_text()
top=top.replace('// Two-entry read pipeline', '// Op17 streams every stage\'s PW and DW weights inside one block transaction.\n// Two-entry read pipeline')
top=top.replace('BADACK=20;', 'BADACK=20,LOADHEAD=21,LOADDATA=22,LOADACK=23,LOADWAIT=24;')
top=top.replace('reg [5:0] count,step,desc_index;', 'reg [5:0] count,step,desc_index;\n reg [4:0] load_stage,load_next;reg load_phase;reg [12:0] load_index;')
top=top.replace('wire final_step=', '''wire [31:0] load_tag=descriptors[load_stage][63:32];
 wire [15:0] load_dimension=load_phase?{10'b0,descriptors[load_stage][21:16]}:16'd256;
 wire [12:0] load_last=load_phase?13'd1023:13'd4351;
 wire final_step=''')
start=top.index(' wire inner_input_valid=');end=top.index(' assign m_axis_tvalid=',start)
top=top[:start]+''' wire inner_input_valid=state==LOADHEAD || state==RUNHEAD || state==RUNMETA ||
   (state==LOADDATA && s_axis_tvalid) || (state==SEND && replay_count!=0);
 wire [127:0] inner_input_data=state==LOADHEAD?
   {load_tag,16'd0,16'd256,load_dimension,3'b0,load_stage,(load_phase?8'd13:8'd12),32'h32434e51}:
   state==RUNHEAD?
   {selected_tag,7'b0,times,16'd256,16'd256,3'b0,selected_slot,8'd14,32'h32434e51}:
   state==RUNMETA?{119'b0,valid_times}:state==SEND?replay_head:s_axis_tdata;
 wire inner_input_last=state==LOADDATA?load_index==load_last:
   state==LOADHEAD || state==RUNHEAD || state==RUNMETA?1'b0:
   state==SEND?read_index==input_beats-1:1'b0;
 wire inner_output_ready=state==LOADACK?1'b1:
   state==ACK?(final_step?m_axis_tready:1'b1):state==OUTPUTS?(final_step?m_axis_tready:1'b1):state==COUNTER;
 assign s_axis_tready=aresetn && (state==IDLE?1'b1:state==LOADDATA?inner_ready:
   state==META || state==DESC || state==LUTIN || state==INPUTS || state==DRAIN);
'''+top[end:]
top=top.replace('qn_short_wide_inner #','qn_stream_inner #')
top=top.replace('state<=IDLE;done<=0;bad<=0;', 'state<=IDLE;done<=0;bad<=0;load_stage<=0;load_next<=LOADHEAD;load_phase<=0;load_index<=0;')
top=top.replace('if(state==INPUTS && !s_axis_tvalid)', 'if((state==INPUTS || state==LOADDATA) && !s_axis_tvalid)')
top=top.replace("         if(s_axis_tdata[39:32]!=15)state<=PASS;\n         else begin", '         begin')
top=top.replace("if(s_axis_tdata[31:0]!=32'h32434e51 ||", "if(s_axis_tdata[39:32]!=17 || s_axis_tdata[31:0]!=32'h32434e51 ||")
top=top.replace('s_axis_tdata[23:16]>32','s_axis_tdata[23:16]>8')
top=top.replace("s_axis_tdata[31:16]!=0 ||", "s_axis_tdata[31:22]!=0 || s_axis_tdata[21:16]==0 || s_axis_tdata[21:16]>41 || !s_axis_tdata[16] ||")
top=top.replace("s_axis_tdata[7:5]!=0 ||", "s_axis_tdata[7:5]!=0 || s_axis_tdata[4:0]!=desc_index ||")
top=top.replace('state<=count==1?INPUTS:LUTIN;', 'load_stage<=0;load_phase<=0;load_index<=0;state<=LOADHEAD;')
needle='       LUTIN:if(accept)begin'
replacement='''       LOADHEAD:if(inner_ready)begin load_index<=0;state<=LOADDATA;end
       LOADDATA:if(accept)begin
         if(s_axis_tlast)begin bad<=1;status<=2;state<=BADACK;end
         else if(load_index==load_last)state<=LOADACK;
         else load_index<=load_index+1;
       end
       LOADACK:if(inner_valid)begin
         if(inner_data[31:0]!=32'h32524e51 || inner_data[63:32]!=0 ||
           inner_data[95:64]!={load_dimension,16'd256} || inner_data[127:96]!=load_tag || !inner_last)
             begin bad<=1;status<=3;state<=DRAIN;end
         else begin
           state<=LOADWAIT;
           if(!load_phase)begin load_phase<=1;load_next<=LOADHEAD;end
           else if(load_stage==count-1)begin step<=0;load_next<=count==1?INPUTS:LUTIN;end
           else begin load_stage<=load_stage+1;load_phase<=0;load_next<=LOADHEAD;end
         end
       end
       LOADWAIT:if(inner_done)state<=load_next;
'''+needle
top=top.replace(needle,replacement)
write('rtl/experimental/qn_stream_axis.sv',top)
print('Created isolated streamed block RTL, 8 PW/DW slots, kernel 1..41, exact float32 requantization')
