"""Isolated 1024-PW/64-DW experiment using the qualified compact quantizer."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
proof=json.loads((ROOT/'reports/fused/compact_requant_evidence.json').read_text())
assert proof['complete'] and not proof['hardware_execution']
for name,value in proof['sources_and_evidence_sha256'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value,name
def write(name,text):
    p=ROOT/name
    if p.exists():assert p.read_text()==text,str(p)
    else:p.write_bytes(text.encode())
text=(ROOT/'rtl/experimental/qn_stream_pw_core.v').read_text()
def replace(old,new):
    global text
    assert old in text,old
    text=text.replace(old,new)
replace('module qn_stream_pw_core','module qn_quad_pw_core')
replace('paired output groups (512 MACs)','four output groups (1024 MACs)')
replace('reg is_quant,is_bulk,payload,header_sent,upper_group;','reg is_quant,is_bulk,payload,header_sent;reg [1:0] upper_group;')
start=text.index(' wire pair_has_upper=');end=text.index(' wire signed [31:0] accum',start)
text=text[:start]+''' wire more_in_quart=upper_group<3 && selected_group<groups-1;
 wire [127:0] input_row;
 wire [511:0] weights;
 genvar wb;
 generate for(wb=0;wb<2;wb=wb+1)begin: weight_banks
  wire [127:0] low_word,high_word;
  wire bank_write=accept && state==WEIGHTS && load_group[1]==wb;
  wire [KW+GW+1:0] a_address=state==WEIGHTS?
   {cache_select[2:0],load_group[GW-1:2],load_group[0],load_k}:
   {cache_select[2:0],compute_group[GW-1:2],1'b0,issued[KW-1:0]};
  wire [KW+GW+1:0] b_address={cache_select[2:0],compute_group[GW-1:2],1'b1,issued[KW-1:0]};
  xpm_memory_tdpram #(.MEMORY_SIZE(8*MAX_K*((MAX_M+15)/16)*64),.MEMORY_PRIMITIVE("ultra"),
   .CLOCKING_MODE("common_clock"),.ECC_MODE("no_ecc"),.USE_MEM_INIT(0),
   .WRITE_DATA_WIDTH_A(128),.WRITE_DATA_WIDTH_B(128),.BYTE_WRITE_WIDTH_A(128),.BYTE_WRITE_WIDTH_B(128),
   .ADDR_WIDTH_A(KW+GW+2),.ADDR_WIDTH_B(KW+GW+2),.READ_DATA_WIDTH_A(128),.READ_DATA_WIDTH_B(128),
   .READ_LATENCY_A(2),.READ_LATENCY_B(2),.WRITE_MODE_A("no_change"),.WRITE_MODE_B("no_change"),.SIM_ASSERT_CHK(1)) weight_memory(
   .clka(aclk),.clkb(aclk),.sleep(1'b0),.ena(issue || bank_write),.wea(bank_write),
   .addra(a_address),.dina(s_axis_tdata),.injectsbiterra(1'b0),.injectdbiterra(1'b0),.rsta(1'b0),.regcea(1'b1),
   .enb(issue),.web(1'b0),.addrb(b_address),.dinb(128'b0),.injectsbiterrb(1'b0),.injectdbiterrb(1'b0),
   .rstb(1'b0),.regceb(1'b1),.douta(low_word),.doutb(high_word),.sbiterra(),.dbiterra(),.sbiterrb(),.dbiterrb());
  assign weights[wb*256+:128]=compute_group+wb*2<groups?low_word:128'b0;
  assign weights[wb*256+128+:128]=compute_group+wb*2+1<groups?high_word:128'b0;
 end endgenerate
'''+text[end:]
replace('accum[0:511]','accum[0:1023]')
replace("wire [8:0] raw_index={output_beat[5:2],5'b0}","wire [9:0] raw_index={output_beat[5:2],6'b0}")
replace('quant_feed[3:0]*32+upper_group*16+lane','quant_feed[3:0]*64+upper_group*16+lane')
replace('fused_affine_quant_exact','fused_affine_quant_compact')
start=text.index(' xpm_memory_tdpram #',text.index(' end endgenerate'))
# First occurrence after banks is the old monolithic weight RAM, after input RAM.
assert 'weight_a_addr' in text[start:text.index(' genvar t,o;',start)]
end=text.index(' genvar t,o;',start);text=text[:start]+text[end:]
replace('for(o=0;o<32;o=o+1)','for(o=0;o<64;o=o+1)')
replace('accum[t*32+o]','accum[t*64+o]')
replace('if(!upper_group && pair_has_upper)begin upper_group<=1;', 'if(more_in_quart)begin upper_group<=upper_group+1;')
replace('compute_group<=compute_group+2','compute_group<=compute_group+4')
write('rtl/experimental/qn_quad_pw_core.v',text)
for source,target in (('qn_adaptive_inner.sv','qn_quad_inner.sv'),('qn_adaptive_axis.sv','qn_quad_axis.sv'),
                      ('fused_depthwise_adaptive.sv','fused_depthwise_quad.sv')):
    text=(ROOT/'rtl/experimental'/source).read_text()
    text=text.replace('qn_adaptive_inner','qn_quad_inner').replace('qn_stream_pw_core','qn_quad_pw_core')
    text=text.replace('fused_depthwise_adaptive','fused_depthwise_quad').replace('fused_affine_quant_exact','fused_affine_quant_compact')
    write('rtl/experimental/'+target,text)
text=(ROOT/'sim/tb_qn_adaptive_axis.sv').read_text().replace('tb_qn_adaptive_axis','tb_qn_quad_compact_axis')
text=text.replace('expected_mac=n*nt*8*256','expected_mac=n*nt*4*256')
write('sim/tb_qn_quad_compact_axis.sv',text)
text=(ROOT/'scripts/adaptive_sim.tcl').read_text().replace('adaptive_sim','quad_compact_sim').replace('tb_qn_adaptive_axis','tb_qn_quad_compact_axis')
text=text.replace('qn_adaptive_axis.sv qn_adaptive_inner.sv qn_stream_pw_core.v fused_depthwise_adaptive.sv fused_affine_quant_exact.sv',
                  'qn_quad_axis.sv qn_quad_inner.sv qn_quad_pw_core.v fused_depthwise_quad.sv fused_affine_quant_compact.sv')
write('scripts/quad_compact_sim.tcl',text)
print('Prepared isolated 1024-MAC block and full protocol regression')
