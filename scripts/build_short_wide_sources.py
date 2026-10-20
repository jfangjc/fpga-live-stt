"""Create an isolated 64-time-lane depthwise experiment; preserve accepted RTL."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parent=json.loads((ROOT/'reports/fused/shortcache_physical_validation.json').read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for name,key in [('software/ort_fpga_shortcache/libort_fpga.so','library_sha256'),
                 ('deployment/experimental-shortcache/qn_tile.ko','driver_sha256'),
                 ('deployment/asr-v3-shortcache/asr-v3-shortcache.bit.bin','firmware_sha256')]:
    assert sha(ROOT/name)==parent[key]
def changed(text,old,new):
    assert old in text,old
    return text.replace(old,new)
primitive=(ROOT/'rtl/experimental/fused_depthwise_channel.sv').read_text()
primitive=changed(primitive,'module fused_depthwise_channel #(parameter MAX_T=4096, MAX_KERNEL=127)',
                  'module fused_depthwise_channel_wide #(parameter MAX_T=256, MAX_KERNEL=21, LANES=64)')
for old,new in [('input wire [127:0] s_data','input wire [LANES*8-1:0] s_data'),
                ('output wire [127:0] m_data','output wire [LANES*8-1:0] m_data'),
                ('localparam AW=$clog2(MAX_T/16),','localparam LW=$clog2(LANES), AW=$clog2(MAX_T/LANES),'),
                ('[0:15]','[0:LANES-1]'),('[127:0] bank_data','[LANES*8-1:0] bank_data'),
                ("{1'b0,time_tile,4'b0}","{1'b0,time_tile,{LW{1'b0}}}"),
                ('reg [3:0] read_rotation','reg [LW-1:0] read_rotation'),
                ('reg [15:0] read_inside','reg [LANES-1:0] read_inside'),
                ('wire [3:0] rotation=base[3:0]','wire [LW-1:0] rotation=base[LW-1:0]'),
                ('wire [511:0] qa,qb,qm','wire [LANES*32-1:0] qa,qb,qm'),
                ('wire [95:0] qs','wire [LANES*6-1:0] qs'),
                ('wire [127:0] qz,qdata','wire [LANES*8-1:0] qz,qdata'),
                ('b<16','b<LANES'),('MAX_T/16-1','MAX_T/LANES-1'),
                ('wire [3:0] displacement','wire [LW-1:0] displacement'),
                ('position[AW+3:4]','position[AW+LW-1:LW]'),
                ('time_tile*16+b','time_tile*LANES+b'),('.LANES(16)','.LANES(LANES)'),
                ('i<16','i<LANES'),('(cfg_times+15)>>4','(cfg_times+LANES-1)>>LW')]:
    primitive=changed(primitive,old,new)
primitive=changed(primitive,' reg signed [8:0] centered;',
    ''' wire [LANES*16-1:0] repeated_bank_data={bank_data,bank_data};
 wire [LANES*8-1:0] rotated_bank_data=repeated_bank_data >> {read_rotation,3'b0};
 reg [LANES*8-1:0] aligned_data;
 reg [LANES-1:0] aligned_inside;
 reg signed [7:0] aligned_weight;
 reg align_valid,aligned_last;
 reg signed [8:0] centered;''')
primitive=changed(primitive,'   product_last<=0;quant_sent<=0;',
    '   aligned_data<=0;aligned_inside<=0;aligned_weight<=0;align_valid<=0;aligned_last<=0;\n   product_last<=0;quant_sent<=0;')
primitive=changed(primitive,'   product_valid<=state==MAC && read_valid;',
    '   align_valid<=state==MAC && read_valid;\n   product_valid<=state==MAC && align_valid;')
primitive=changed(primitive,'''   if(state==MAC && read_valid)begin
    product_last<=read_tap==kernel-1;''', '''   if(state==MAC && read_valid)begin
    aligned_data<=rotated_bank_data;aligned_inside<=read_inside;
    aligned_weight<=$signed(weights[read_tap*8+:8]);aligned_last<=read_tap==kernel-1;
   end
   if(state==MAC && align_valid)begin
    product_last<=aligned_last;''')
primitive=changed(primitive,"centered=read_inside[i]?$signed({1'b0,bank_data[((i+read_rotation)%16)*8+:8]})",
                  "centered=aligned_inside[i]?$signed({1'b0,aligned_data[i*8+:8]})")
primitive=changed(primitive,'centered*$signed(weights[read_tap*8+:8])','centered*aligned_weight')
primitive=changed(primitive,'tap<=0;read_valid<=0;product_valid<=0;quant_sent<=0;state<=MAC;',
                  'tap<=0;read_valid<=0;align_valid<=0;product_valid<=0;quant_sent<=0;state<=MAC;')
primitive=primitive.replace('// Odd symmetric kernels, stride/dilation one. Sixteen time lanes per tap.',
                            '// Odd symmetric kernels, stride/dilation one. 64 time lanes per tap, pipelined rotation.')
wrapper=(ROOT/'rtl/experimental/qn_short_cache_axis.sv').read_text()
wrapper=wrapper[wrapper.index('module qn_cached_axis'):]
wrapper='// Isolated 32-slot protocol-compatible experiment: 512 PW MACs, 64 DW time lanes.\n'+wrapper
wrapper=changed(wrapper,' wire [127:0] dm_data;', ''' wire [511:0] dw_wide_data;
 reg [511:0] input_pack;
 reg [1:0] input_part,output_part;
 reg input_pending;
 reg [12:0] output_word;
 wire [127:0] dm_data=dw_wide_data[output_part*128+:128];
 wire output_part_final=output_part==3 || output_word==((times+15)>>4)-1;
 always @(posedge aclk)begin
  if(!aresetn || (state==CONFIG && dc_ready))begin
   input_pack<=0;input_part<=0;input_pending<=0;output_part<=0;output_word<=0;
  end else begin
   if(state==CHANNEL && accept)begin
    input_pack[input_part*128+:128]<=s_axis_tdata;
    if(input_part==3 || received_tiles==((times+15)>>4)-1)begin input_pending<=1;input_part<=0;end
    else input_part<=input_part+1;
   end
   if(state==CHANNEL && input_pending && ds_ready)begin input_pending<=0;input_pack<=0;end
   if(in_pair && dm_valid && cs_ready)begin
    output_word<=output_word+1;
    if(output_part_final)output_part<=0;else output_part<=output_part+1;
   end
  end
 end''')
wrapper=changed(wrapper,'in_pair?(dm_last && channel==channels-1)',
                  'in_pair?(dm_last && output_part_final && channel==channels-1)')
wrapper=changed(wrapper,'state==CHANNEL?ds_ready:1\'b0','state==CHANNEL?(ds_ready && !input_pending):1\'b0')
wrapper=changed(wrapper,'fused_depthwise_channel #(.MAX_T(256),.MAX_KERNEL(21))',
                  'fused_depthwise_channel_wide #(.MAX_T(256),.MAX_KERNEL(21),.LANES(64))')
wrapper=changed(wrapper,'.s_data(s_axis_tdata),.s_valid(state==CHANNEL && s_axis_tvalid)',
                  '.s_data(input_pack),.s_valid(state==CHANNEL && input_pending)')
wrapper=changed(wrapper,'.m_data(dm_data),.m_valid(dm_valid),.m_ready(cs_ready && in_pair)',
                  '.m_data(dw_wide_data),.m_valid(dm_valid),.m_ready(cs_ready && in_pair && output_part_final)')
files={'rtl/experimental/fused_depthwise_channel_wide.sv':primitive,
       'rtl/experimental/qn_short_wide_axis.sv':wrapper}
for name,content in files.items():
    path=ROOT/name;assert not path.exists(),f'Refusing to overwrite {path}'
    path.write_bytes(content.encode())
for kind in ('sim','synth'):
    source=(ROOT/f'scripts/short_cache_{kind}.tcl').read_text()
    source=source.replace('short_cache_sim','short_wide_sim').replace('short_cache_system','short_wide_system')
    source=source.replace('Prototype_v3_short_cache','Prototype_v3_short_wide')
    source=source.replace('qn_short_cache_axis.sv','qn_short_wide_axis.sv')
    source=source.replace('fused_depthwise_channel.sv','fused_depthwise_channel_wide.sv')
    source=source.replace('short_cache_synth_utilization.rpt','short_wide_synth_utilization.rpt')
    source=source.replace('SHORT_CACHE_SYNTH_COMPLETE','SHORT_WIDE_SYNTH_COMPLETE')
    # Preserve the existing testbench module/file; it verifies the unchanged ABI.
    source=source.replace('tb_qn_short_wide_axis','tb_qn_short_cache_axis')
    path=ROOT/f'scripts/short_wide_{kind}.tcl';assert not path.exists()
    path.write_bytes(source.encode())
print(json.dumps({'preserved_validated_parent':True,'new_sources':{name:sha(ROOT/name) for name in files}}))
