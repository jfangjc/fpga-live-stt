"""Generate a separate four-slot, fixed-256-channel retained-pair experiment."""
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def replace(text,old,new,count=None):
    hits=text.count(old)
    assert hits and (count is None or hits==count),(old,hits,count)
    return text.replace(old,new)


def write(path,text):
    """Keep generated sources stable during Vivado runs; shell files need LF."""
    data=text.encode('utf-8')
    if not path.exists() or path.read_bytes()!=data:path.write_bytes(data)


def software():
    source=ROOT/'software/ort_fpga_pair';target=ROOT/'software/ort_fpga_cache'
    target.mkdir(exist_ok=True)
    shutil.copytree(source/'include',target/'include',dirs_exist_ok=True)
    for name in ('build.sh','qnc.h','pointwise.cc','qnc_transport.c','graph.py','smoke.py','validate.py',
                 'benchmark.py','benchmark_block.py','run_latency_checks.py'):
        shutil.copy2(source/name,target/name)
    p=target/'pointwise.cc';s=p.read_text()
    s=replace(s,'const void* resident=nullptr;','const void* residents[4]={};',1)
    s=replace(s,'parameters/pair_protocol','parameters/cache_protocol',1)
    s=replace(s,'protocol==1','protocol==1',1)
    s=replace(s,'require(xs[1]==dw.m,"Input channels changed");',
              'require(xs[1]==dw.m && dw.m==256 && pw.m==256 && pw.k==256,"Cache requires fixed 256-channel pairs");',1)
    begin=s.index('   int rc=0;\n   if(resident!=this)')
    end=s.index('   physical_calls++;',begin)
    s=s[:begin]+'''   unsigned slot=4;
   for(unsigned i=0;i<4;i++)if(residents[i]==this){slot=i;break;}
   bool needs_load=slot==4;
   if(needs_load){for(unsigned i=0;i<4;i++)if(!residents[i]){slot=i;break;}}
   require(slot<4,"At most four resident physical kernels per library are supported");
   int rc=qnc_select_slot(device,slot);
   if(!rc && needs_load){
    rc=qnc_load_quant(device,pw.w.data(),unsigned(pw.m),unsigned(pw.k),corrections.data(),pw.mult.data(),pw.shifts.data(),pw.zy);
    if(!rc)rc=qnc_load_depthwise(device,dw.w.data(),dw.bias.data(),dw.mult.data(),dw.shifts.data(),dw.zx,dw.zy);
    if(!rc)residents[slot]=this;
   }
   if(!rc)rc=qnc_run_pair(device,x,t,valid_t,y);
   if(rc){for(auto& owner:residents)owner=nullptr;throw std::runtime_error("Cached FPGA transport failed: "+std::to_string(rc));}
''' +s[end:]
    s=replace(s,'if(resident==p)resident=nullptr;','for(auto& owner:residents)if(owner==p)owner=nullptr;',1)
    s=replace(s,'prototype.fpga.pair','prototype.fpga.cache',1);write(p,s)
    p=target/'qnc_transport.c';s=p.read_text()
    s=replace(s,'struct qnc { int fd;',
              'struct slot_state { unsigned k,m,tag; int valid,quantized,dw_valid; };\nstruct qnc { unsigned slot; struct slot_state slots[4]; int fd;',1)
    insertion='''int qnc_select_slot(qnc *c,unsigned slot) {
 if(!c || slot>=4)return -EINVAL;
 c->slots[c->slot]=(struct slot_state){c->k,c->m,c->tag,c->valid,c->quantized,c->dw_valid};
 c->slot=slot;struct slot_state *p=&c->slots[slot];
 c->k=p->k;c->m=p->m;c->tag=p->tag;c->valid=p->valid;c->quantized=p->quantized;c->dw_valid=p->dw_valid;
 return 0;
}
'''
    s=replace(s,'static void put32(',insertion+'static void put32(',1)
    s=replace(s,'if(rc) c->valid=0;',
              'if(rc){c->valid=0;c->dw_valid=0;for(unsigned i=0;i<4;i++)c->slots[i].valid=c->slots[i].dw_valid=0;}',1)
    s=replace(s,'header(c->tx,bias?4:1,k,m,c->tag);',
              'header(c->tx,9,k,m,c->tag);c->tx[5]=(uint8_t)c->slot;',1)
    s=replace(s,'header(c->tx,pair?8:6,c->k,c->m,c->tag);',
              'header(c->tx,11,c->k,c->m,c->tag);c->tx[5]=(uint8_t)c->slot;',1)
    s=replace(s,'header(c->tx,7,c->k,11,c->tag);',
              'header(c->tx,10,c->k,11,c->tag);c->tx[5]=(uint8_t)c->slot;',1)
    write(p,s)
    p=target/'qnc.h';s=p.read_text().replace('int qnc_load(qnc *ctx,','int qnc_select_slot(qnc *ctx, unsigned slot);\nint qnc_load(qnc *ctx,',1);write(p,s)
    p=target/'graph.py';s=p.read_text().replace('def candidate(','def one_pair(',1)
    s=s.replace("g.opset_import.append(helper.make_opsetid('prototype.fpga.pair',1))",
                "if not any(v.domain=='prototype.fpga.pair' for v in g.opset_import): g.opset_import.append(helper.make_opsetid('prototype.fpga.pair',1))",1)
    s+='''

def candidate(model, oracle=False):
    g=copy.deepcopy(model)
    names={n.name for n in g.graph.node}
    replaced=0
    for index in (0,5,10,15):
        dw=f'/encoder/encoder.1/mconv.{index}/conv/Conv_quant'
        pw=f'/encoder/encoder.1/mconv.{index+1}/conv/Conv_quant'
        if dw in names and pw in names:
            g=one_pair(g,dw,pw,oracle);replaced+=1
    assert replaced in (1,4), 'Expected the four model pairs or one extracted pair'
    for n in g.graph.node:
        if n.domain=='prototype.fpga.pair':n.domain='prototype.fpga.cache'
    for v in g.opset_import:
        if v.domain=='prototype.fpga.pair':v.domain='prototype.fpga.cache'
    onnx.checker.check_model(g)
    return g
'''
    write(p,s)
    for name in ('validate.py','benchmark.py','benchmark_block.py','run_latency_checks.py'):
        p=target/name;s=p.read_text()
        s=s.replace('asr-v3-pair','asr-v3-cache').replace('experimental-pair','experimental-cache')
        s=s.replace('pair_physical_validation','cache_physical_validation').replace('pair_irq_restoration','cache_irq_restoration')
        if name=='run_latency_checks.py':
            s=s.replace("f'reports/fused/pair_","f'reports/fused/cache_")
            s=replace(s,"('benchmark.py',100,'total')","('benchmark.py',300,'total')",1)
        if name=='validate.py':
            s=replace(s,"(1 if name=='fpga' else 0)","(4 if name=='fpga' else 0)",1)
            s=replace(s,"(1 if name=='oracle' else 0)","(4 if name=='oracle' else 0)",1)
        if name=='benchmark.py':
            s=replace(s,"(kind=='fpga')","(4 if kind=='fpga' else 0)",1)
            s=replace(s,"(kind=='oracle')","(4 if kind=='oracle' else 0)",1)
            s=replace(s,"['ioctls']==1","['ioctls']==4",1)
            s=s.replace("'runtime':'pair'","'runtime':'cache'")
        write(p,s)
    p=target/'smoke.py';s=p.read_text();begin=s.index('[(1,1,1,1,0,255,0)');end=s.index(']:',begin)
    s=s[:begin]+'''[(256,256,1,1,0,255,0),(256,256,17,13,255,0,255),
                                  (256,256,51,51,37,129,7),(256,256,51,51,128,127,128),
                                  (256,256,101,99,220,37,129),(256,256,33,0,0,255,255)'''+s[end:]
    s=s.replace('prototype.fpga.pair','prototype.fpga.cache');write(p,s)


def driver():
    source=ROOT/'deployment/experimental-pair';target=ROOT/'deployment/experimental-cache'
    target.mkdir(exist_ok=True)
    for name in ('qn_tile.c','qn_tile_uapi.h','qn_layer_protocol.h','Makefile'):
        shutil.copy2(source/name,target/name)
    write(target/'qn_cache_protocol.h','''/* SPDX-License-Identifier: GPL-2.0 */
#ifndef QN_CACHE_PROTOCOL_H
#define QN_CACHE_PROTOCOL_H
#include "qn_layer_protocol.h"
/* Normalize a private packet during validation, restoring every byte before DMA. */
static inline int qn_cache_validate(void *packet, __u32 input_bytes,
                                   __u32 output_bytes, struct qn_layer_command *c)
{
 unsigned char *h=packet;
 unsigned char op,flags;
 int result;
 if(input_bytes<16)return -EINVAL;
 op=h[4];flags=h[5];
 if(flags>3 || (op!=9 && op!=10 && op!=11) ||
    (get_unaligned_le32(h+8)&0xffff)!=256 ||
    (get_unaligned_le32(h+4)>>16)!=(op==10?11:256))return -EINVAL;
 h[4]=op==9?4:op==10?7:8;h[5]=0;
 result=qn_layer_validate(packet,input_bytes,output_bytes,c);
 h[4]=op;h[5]=flags;c->op=op;
 return result;
}
#endif
''')
    p=target/'qn_tile.c';s=p.read_text()
    s=replace(s,'#include "qn_layer_protocol.h"','#include "qn_cache_protocol.h"',1)
    s=replace(s,'struct file *cache_owner;',
              'struct file *slot_owner[4];u32 slot_tag[4];bool slot_dw_valid[4];\n\tstruct file *cache_owner;',1)
    s=replace(s,'static void qn_reset(struct qn_tile *q)\n{',
              'static void qn_reset(struct qn_tile *q)\n{\n\tmemset(q->slot_owner,0,sizeof(q->slot_owner));\n\tmemset(q->slot_dw_valid,0,sizeof(q->slot_dw_valid));',1)
    s=replace(s,'static int qn_release(struct inode *inode, struct file *file)\n{',
              'static int qn_release(struct inode *inode, struct file *file)\n{\n\tunsigned slot;',1)
    s=replace(s,'\tif (q->cache_owner == file) {',
              '\tfor(slot=0;slot<4;slot++)if(q->slot_owner[slot]==file){q->slot_owner[slot]=NULL;q->slot_dw_valid[slot]=false;}\n\tif (q->cache_owner == file) {',1)
    s=replace(s,'int ret, status;', 'int ret, status;\n unsigned layer_slot=0;',1)
    s=replace(s,'if (cmd == QN_TILE_RUN || cmd == QN_TILE_RUN_BATCH)',
              'if (cmd != QN_LAYER_EXCHANGE)',1)
    begin=s.index('\t\tret = cached_batch ? qn_layer_validate_batch(')
    end=s.index('\t} else for (i = 0; i < count; i++)',begin)
    s=s[:begin]+'''        ret=qn_cache_validate(q->input,packet_bytes,rx_stride,&command);
        if(ret)goto unlock;
        layer_op=command.op;layer_k=command.k;layer_m=command.m;layer_tag=command.tag;
        layer_slot=((u8*)q->input)[5];
        if(layer_op!=9 && (q->slot_owner[layer_slot]!=file ||
           q->slot_tag[layer_slot]!=layer_tag || (layer_op==11 && !q->slot_dw_valid[layer_slot]))){
            ret=-ESTALE;goto unlock;
        }
        if(layer_op==9){q->slot_owner[layer_slot]=NULL;q->slot_dw_valid[layer_slot]=false;}
        if(layer_op==10)q->slot_dw_valid[layer_slot]=false;
''' +s[end:]
    begin=s.index('\t\tif (layer_op == 7) q->dw_valid = true;')
    end=s.index('\n\t}\n\tret = copy_to_user',begin)
    s=s[:begin]+'''        if(layer_op==10)q->slot_dw_valid[layer_slot]=true;
        if(layer_op==9){q->slot_owner[layer_slot]=file;q->slot_tag[layer_slot]=layer_tag;}
''' +s[end:]
    s=s.replace('pair_protocol','cache_protocol')
    write(p,s)


def application():
    source=ROOT/'deployment/asr-v3-pair';target=ROOT/'deployment/asr-v3-cache'
    target.mkdir(exist_ok=True)
    for name in ('asr-v3-pair.dts','shell.json','activate.sh'):
        text=(source/name).read_text().replace('asr-v3-pair','asr-v3-cache').replace('experimental-pair','experimental-cache')
        text=text.replace('pair_firmware_evidence.json','cache_firmware_evidence.json').replace('pair_protocol','cache_protocol')
        write(target/name.replace('asr-v3-pair','asr-v3-cache'),text)
    text=(ROOT/'scripts/run_pair_physical.sh').read_text()
    text=text.replace('asr-v3-pair','asr-v3-cache').replace('ort_fpga_pair','ort_fpga_cache').replace('pair_physical_','cache_physical_')
    text=text.replace('Pair physical','Cache physical')
    text=text.replace('restore_bulk\necho', '.venv/bin/python software/ort_fpga_cache/check_resident.py\nrestore_bulk\necho')
    write(ROOT/'scripts/run_cache_physical.sh',text)


def evidence():
    text=(ROOT/'scripts/prepare_pair_firmware.py').read_text()
    text=text.replace('asr-v3-pair','asr-v3-cache').replace('asr_v3_pair.xsa','asr_v3_cache.xsa')
    text=text.replace('fused_system','pair_cache_system').replace('Prototype_v3_fused_pair','Prototype_v3_pair_cache')
    text=text.replace('ort_fpga_pair','ort_fpga_cache').replace('experimental-pair','experimental-cache')
    text=text.replace('pair_firmware_evidence','cache_firmware_evidence').replace('pair_native_','cache_native_')
    text=text.replace('fused_pair_sim','pair_cache_sim').replace('qn_fused_axis','qn_pair_cache_axis').replace('qn_fused_core','qn_pair_cache_core')
    text=text.replace('tb_qn_fused_axis','tb_qn_pair_cache_axis').replace('fused depthwise/pointwise arithmetic','four-slot retained pair arithmetic')
    begin=text.index("    protocol=(r/'pair_driver_protocol.log').read_text()")
    end=text.index("    accepted=read(r/'short_half_second_deployment.json')",begin)
    text=text[:begin]+'''    assert 'PASS: 36912 cache slot packet' in (r/'cache_driver_protocol.log').read_text()
    assert 'PASS: four-slot transport residency' in (r/'cache_transport.log').read_text()
    assert 'PASS: 26 four-slot retained pair arithmetic' in (r/'pair_cache_sim.log').read_text()
    previous=read(r/'pair_firmware_evidence.json')
    for name in ('rtl/experimental/fused_depthwise_channel.sv','rtl/experimental/fused_affine_quant.v'):
        assert sha(ROOT/name)==previous['sources_and_evidence_sha256'][name]
    pair=read(r/'pair_physical_validation.json')
    for name,key in [('software/ort_fpga_pair/libort_fpga.so','library_sha256'),
                     ('deployment/experimental-pair/qn_tile.ko','driver_sha256'),
                     ('deployment/asr-v3-pair/asr-v3-pair.bit.bin','firmware_sha256')]:
        assert sha(ROOT/name)==pair[key]
''' +text[end:]
    text=text.replace("'pair_driver_protocol.log'","'cache_driver_protocol.log','cache_transport.log'")
    text=text.replace("ROOT/'scripts/fused_system_build.tcl'","ROOT/'scripts/pair_cache_system_build.tcl'")
    text=text.replace("ROOT/'scripts/pair_cache_sim.tcl'","ROOT/'scripts/pair_cache_sim.tcl',ROOT/'scripts/build_pair_cache_sources.py',ROOT/'deployment/experimental-cache/qn_cache_protocol.h'")
    write(ROOT/'scripts/prepare_cache_firmware.py',text)


def main():
    rtl=ROOT/'rtl/experimental'
    core=(rtl/'qn_fused_core.v').read_text()
    core=replace(core,'module qn_bulk_core #(parameter MAX_K=1024,parameter MAX_M=1024)',
                 'module qn_pair_cache_core #(parameter MAX_K=256,parameter MAX_M=256)',1)
    core=replace(core,'output wire busy,output reg done,output reg error);',
                 'input wire [1:0] cache_select, output wire busy,output reg done,output reg error);',1)
    core=replace(core,'reg cache_valid,cache_quant,is_quant,is_bulk,payload,header_sent,upper_group;',
                 'reg [3:0] slot_valid,slot_quant;\n reg [15:0] slot_k[0:3],slot_m[0:3];\n reg [31:0] slot_tag[0:3];\n wire cache_valid=slot_valid[cache_select],cache_quant=slot_quant[cache_select];\n wire [15:0] cache_k=slot_k[cache_select],cache_m=slot_m[cache_select];\n wire [31:0] cache_tag=slot_tag[cache_select];\n reg is_quant,is_bulk,payload,header_sent,upper_group;',1)
    core=replace(core,'request_k,request_m,request_t,cache_k,cache_m','request_k,request_m,request_t',1)
    core=replace(core,'tag,cache_tag,status','tag,status',1)
    # Slot occupies output-group bank bits. Each pair uses sixteen 16-output groups.
    core=replace(core,'wire [KW+GW-1:0] weight_a_addr=', 'wire [KW+GW+1:0] weight_a_addr=',1)
    core=replace(core,'{load_group,load_k} : {compute_group,issued[KW-1:0]}',
                 '{cache_select,load_group,load_k} : {cache_select,compute_group,issued[KW-1:0]}',1)
    core=replace(core,'wire [KW+GW-1:0] weight_b_addr={high_group,issued[KW-1:0]};',
                 'wire [KW+GW+1:0] weight_b_addr={cache_select,high_group,issued[KW-1:0]};',1)
    core=replace(core,'params[0:(MAX_M+15)/16-1]','params[0:4*((MAX_M+15)/16)-1]',1)
    core=replace(core,'params[load_group]','params[{cache_select,load_group}]',1)
    core=replace(core,'params[selected_group]','params[{cache_select,selected_group}]',4)
    core=replace(core,'(1<<(KW+GW))*128','(1<<(KW+GW+2))*128',1)
    core=replace(core,'.ADDR_WIDTH_A(KW+GW),.ADDR_WIDTH_B(KW+GW)',
                 '.ADDR_WIDTH_A(KW+GW+2),.ADDR_WIDTH_B(KW+GW+2)',1)
    # All cache writes refer to the selected slot. Reset clears every slot.
    for old,new in [('cache_valid<=','slot_valid[cache_select]<='),('cache_quant<=','slot_quant[cache_select]<='),
                    ('cache_k<=','slot_k[cache_select]<='),('cache_m<=','slot_m[cache_select]<='),('cache_tag<=','slot_tag[cache_select]<=')]:
        core=replace(core,old,new)
    core=replace(core,'state<=HEADER;slot_valid[cache_select]<=0;slot_quant[cache_select]<=0;',
                 'state<=HEADER;slot_valid<=0;slot_quant<=0;',1)
    core=replace(core,'slot_k[cache_select]<=0;slot_m[cache_select]<=0;tag<=0;slot_tag[cache_select]<=0;',
                 'tag<=0;for(integer reset_slot=0;reset_slot<4;reset_slot=reset_slot+1)begin slot_k[reset_slot]<=0;slot_m[reset_slot]<=0;slot_tag[reset_slot]<=0;end ',1)
    core=replace(core,'for(integer reset_slot=0;','for(reset_slot=0;',1)
    core=replace(core,'reg [3:0] state;','integer reset_slot;\n reg [3:0] state;',1)
    write(rtl/'qn_pair_cache_core.v',core)
    wrapper=(rtl/'qn_fused_axis.sv').read_text()
    wrapper=replace(wrapper,'parameter MAX_K=1024,parameter MAX_M=1024','parameter MAX_K=256,parameter MAX_M=256',1)
    wrapper=replace(wrapper,'reg dw_cache,local_error;',
                    'reg [3:0] slot_dw_valid;reg [31:0] slot_dw_tag[0:3];\n reg [1:0] slot;wire [1:0] header_slot=s_axis_tdata[41:40];\n wire [1:0] core_slot=state==HEADER?header_slot:slot;\n wire dw_cache=slot_dw_valid[header_slot];wire [31:0] dw_tag=slot_dw_tag[header_slot];\n reg local_error;',1)
    wrapper=replace(wrapper,'reg [31:0] dw_tag,tag,status;','reg [31:0] tag,status;',1)
    wrapper=replace(wrapper,'s_axis_tdata[47:40]==0','s_axis_tdata[47:42]==0')
    wrapper=replace(wrapper,'hk>0 && hk<=MAX_K && hm==11','hk==256 && hm==11',1)
    wrapper=replace(wrapper,'hk>0 && hk<=MAX_K && hm>0 && hm<=MAX_M','hk==256 && hm==256',1)
    wrapper=replace(wrapper,' && hk==cached_channels','',1)
    wrapper=replace(wrapper,'op==7','op==10')
    wrapper=replace(wrapper,'op==8','op==11')
    wrapper=replace(wrapper,'dw_weights[0:MAX_K-1]','dw_weights[0:1023]',1)
    wrapper=replace(wrapper,'dw_params[0:MAX_K-1]','dw_params[0:1023]',1)
    wrapper=replace(wrapper,'dw_params[channel]','dw_params[{slot,channel[7:0]}]')
    wrapper=replace(wrapper,'dw_weights[channel]','dw_weights[{slot,channel[7:0]}]')
    wrapper=replace(wrapper,'in_pair?dm_data:s_axis_tdata;',
                    "in_pair?dm_data:state==HEADER?{s_axis_tdata[127:48],8'b0,8'd4,s_axis_tdata[31:0]}:s_axis_tdata;",1)
    wrapper=replace(wrapper,'qn_bulk_core #','qn_pair_cache_core #',1)
    wrapper=replace(wrapper,'.aclk(aclk),.aresetn(aresetn),.s_axis_tdata(cs_data)',
                    '.aclk(aclk),.aresetn(aresetn),.cache_select(core_slot),.s_axis_tdata(cs_data)',1)
    wrapper=replace(wrapper,'state<=HEADER;dw_cache<=0;local_error<=0;',
                    'state<=HEADER;slot_dw_valid<=0;slot<=0;local_error<=0;',1)
    wrapper=replace(wrapper,'dw_tag<=0;tag<=0;',
                    'for(integer reset_slot=0;reset_slot<4;reset_slot=reset_slot+1)slot_dw_tag[reset_slot]<=0;tag<=0;',1)
    wrapper=replace(wrapper,'channels<=hk;outputs<=hm;tag<=',
                    'slot<=header_slot;channels<=hk;outputs<=hm;tag<=',1)
    wrapper=replace(wrapper,'dw_cache<=0;','slot_dw_valid[slot]<=0;')
    # HEADER sees the new slot before its register updates.
    wrapper=replace(wrapper,'if(op==10)begin\n      slot_dw_valid[slot]<=0;',
                    'if(op==10)begin\n      slot_dw_valid[header_slot]<=0;',1)
    wrapper=replace(wrapper,'if(op==1 || op==3 || op==4)slot_dw_valid[slot]<=0;',
                    'slot_dw_valid[header_slot]<=0;',1)
    wrapper=replace(wrapper,'dw_tag<=tag;dw_cache<=1;',
                    'slot_dw_tag[slot]<=tag;slot_dw_valid[slot]<=1;',1)
    # Reject all other commands locally. Only a fixed-256 LOAD_SLOT can enter core.
    wrapper=replace(wrapper,'wire intercepted=op==10 || op==11;',
                    "wire load_header_valid=op==9 && s_axis_tdata[31:0]==32'h32434e51 && s_axis_tdata[47:42]==0 && hk==256 && hm==256 && ht==0 && s_axis_tdata[127:96]!=0 && !s_axis_tlast;\n wire intercepted=!load_header_valid;",1)
    wrapper=replace(wrapper,'state==HEADER?(op==10 || (op==11 && !pair_header_valid)?1\'b1:cs_ready)',
                    'state==HEADER?(intercepted?1\'b1:cs_ready)',1)
    wrapper=replace(wrapper,'end else begin\n      // Any pointwise weight load/invalidation invalidates the paired DW cache.',
                    'end else if(load_header_valid)begin\n      // Only this slot is invalidated by its pointwise load.',1)
    wrapper=replace(wrapper,'state<=PASS;\n     end\n    end',
                    'state<=PASS;\n     end else begin local_error<=1;status<=1;state<=s_axis_tlast?ACK:DRAIN;end\n    end',1)
    wrapper='// Four resident 256x256 DW11/PW pairs: LOAD_SLOT=9, LOAD_DW_SLOT=10, RUN_SLOT=11.\n// Header flag low two bits select a slot; no legacy commands are supported.\n'+wrapper
    write(rtl/'qn_pair_cache_axis.sv',wrapper)
    tb=(ROOT/'sim/tb_qn_fused_axis.sv').read_text().replace('tb_qn_fused_axis','tb_qn_pair_cache_axis')
    tb=replace(tb,'integer j;','integer j,test_slot=0;',1)
    tb=replace(tb,"m[15:0],8'b0,op[7:0]","m[15:0],test_slot[7:0],op[7:0]",1)
    tb=replace(tb,'header(q?4:1,','header(9,',1)
    tb=replace(tb,'header(7,','header(10,',1)
    tb=replace(tb,'header(8,','header(11,',3)
    tb=tb[:tb.index(' initial begin')]+''' initial begin
  repeat(5)@(negedge clk);rstn=1;
  for(test_slot=0;test_slot<4;test_slot=test_slot+1)begin
   load(256,256,11+test_slot*5,101+test_slot,127-test_slot*17,128+test_slot*13,1);
   load_dw(256,11+test_slot*5,101+test_slot,128+test_slot*17,127-test_slot*17);
  end
  for(test_slot=3;test_slot>=0;test_slot=test_slot-1)
   pair_case(256,256,17,13,11+test_slot*5,101+test_slot,128+test_slot*17,127-test_slot*17,128+test_slot*13);
  test_slot=0;pair_case(256,256,51,51,11,101,128,127,128);
  test_slot=3;pair_case(256,256,101,99,26,104,179,76,167);
  // Replacing one PW slot invalidates only its DW ownership.
  test_slot=2;load(256,256,44,202,37,129,1);
  expect_ack(3,256,256,202,0,0,0);send(header(11,256,256,17,202),0);send(0,1);finish(1);
  test_slot=1;pair_case(256,256,17,0,16,102,145,110,141);
  test_slot=2;load_dw(256,44,202,220,37);pair_case(256,256,17,13,44,202,220,37,129);
  // Reset invalidates every slot; stale requests must fail without touching core.
  rstn=0;repeat(3)@(negedge clk);rstn=1;
  for(test_slot=0;test_slot<4;test_slot=test_slot+1)begin
   expect_ack(3,256,256,101+test_slot,0,0,0);
   send(header(11,256,256,17,101+test_slot),0);send(0,1);finish(1);
  end
  test_slot=0;load(256,256,11,301,127,128,1);load_dw(256,11,301,128,127);
  pair_case(256,256,17,13,11,301,128,127,128);
  $display("PASS: %0d four-slot retained pair arithmetic, independent weights, cache invalidation, counters, stalls and reset cases",cases);$finish;
 end
endmodule
'''
    write(ROOT/'sim/tb_qn_pair_cache_axis.sv',tb)
    sim=(ROOT/'scripts/fused_pair_sim.tcl').read_text().replace('fused_pair_sim','pair_cache_sim')
    sim=sim.replace('qn_fused_axis.sv','qn_pair_cache_axis.sv').replace('qn_fused_core.v','qn_pair_cache_core.v').replace('tb_qn_fused_axis','tb_qn_pair_cache_axis')
    sim=sim.replace('fused depthwise/pointwise arithmetic','four-slot retained pair arithmetic')
    write(ROOT/'scripts/pair_cache_sim.tcl',sim)
    build=(ROOT/'scripts/fused_system_build.tcl').read_text()
    build=build.replace('fused_system','pair_cache_system').replace('Prototype_v3_fused_pair','Prototype_v3_pair_cache')
    build=build.replace('qn_fused_axis.sv','qn_pair_cache_axis.sv').replace('qn_fused_core.v','qn_pair_cache_core.v')
    build=build.replace('asr-v3-pair','asr-v3-cache').replace('asr_v3_pair.xsa','asr_v3_cache.xsa')
    build=build.replace('validate_bd_design','set_property -dict [list CONFIG.MAX_K {256} CONFIG.MAX_M {256}] [get_bd_cells asr_v2_system/tile]\nvalidate_bd_design',1)
    build=build.replace('[get_bd_cells asr_v2_system/tile]', '[get_bd_cells tile]')
    build=build.replace('FUSED_PAIR_FIRMWARE_EXPORT_COMPLETE','PAIR_CACHE_FIRMWARE_EXPORT_COMPLETE')
    # A stale module-reference checkpoint must be rebuilt before parent synthesis.
    build=build.replace('launch_runs synth_1 -jobs 4',
                        'set cache_tile_run [get_runs -quiet asr_v2_system_tile_0_synth_1]\nif {[llength $cache_tile_run]} {reset_run $cache_tile_run}\nreset_run synth_1\nreset_run impl_1\nlaunch_runs synth_1 -jobs 4',1)
    write(ROOT/'scripts/pair_cache_system_build.tcl',build)
    software()
    driver()
    application()
    evidence()
    print('Separate four-slot RTL generated; no verified pair sources modified.')


if __name__=='__main__':main()
