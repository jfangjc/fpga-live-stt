"""Generate an isolated 32-slot short-window experiment from validated cache RTL.

Never run this while its Vivado project is active. The four-slot sources remain
untouched. Fixed 256 channels, odd kernels 11 through 21, physical T <= 256.
"""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1]

def change(s,a,b,n=None):
    count=s.count(a)
    assert count and (n is None or count==n),(a,count,n)
    return s.replace(a,b)

def write(p,s):
    p.parent.mkdir(parents=True,exist_ok=True)
    data=s.encode('utf-8')
    if not p.exists() or p.read_bytes()!=data:p.write_bytes(data)

def native():
    src=ROOT/'software/ort_fpga_cache';dst=ROOT/'software/ort_fpga_shortcache'
    shutil.copytree(src/'include',dst/'include',dirs_exist_ok=True)
    for name in ('build.sh','qnc.h','pointwise.cc','qnc_transport.c','graph.py','smoke.py','benchmark.py','benchmark_block.py','run_latency_checks.py'):
        s=(src/name).read_text()
        s=s.replace('prototype.fpga.cache','prototype.fpga.shortcache').replace('asr-v3-cache','asr-v3-shortcache')
        s=s.replace('experimental-cache','experimental-shortcache').replace('cache_physical_validation','shortcache_physical_validation')
        if name=='pointwise.cc':
            s=change(s,'residents[4]','residents[32]',1)
            s=change(s,'parameters/cache_protocol','parameters/short_cache_protocol',1)
            s=change(s,'width==11','width>=11 && width<=21 && (width&1)',1)
            s=change(s,'xs[2]<=4096','xs[2]<=(emulate?4096:256)',1)
            s=change(s,'tap<11','tap<dw.width',1)
            s=change(s,'+tap-5','+tap-dw.width/2',1)
            s=change(s,'channel*11+tap','channel*dw.width+tap',1)
            s=change(s,'unsigned slot=4;','unsigned slot=32;',1)
            s=change(s,'i<4','i<32')
            s=change(s,'slot==4','slot==32',1)
            s=change(s,'slot<4,"At most four','slot<32,"At most thirty-two',1)
            s=change(s,'dw.shifts.data(),dw.zx,dw.zy','dw.shifts.data(),dw.zx,dw.zy,unsigned(dw.width)',1)
        elif name=='qnc.h':
            s=change(s,'uint8_t xzero, uint8_t yzero);','uint8_t xzero, uint8_t yzero, unsigned kernel);',1)
        elif name=='qnc_transport.c':
            s=change(s,'slots[4]','slots[32]',1)
            s=change(s,'slot>=4','slot>=32',1)
            s=change(s,'i<4;i++)c->slots','i<32;i++)c->slots',1)
            s=change(s,'header(c->tx,9,','header(c->tx,12,',1)
            s=change(s,'header(c->tx,11,','header(c->tx,14,',1)
            s=change(s,'t>4096','t>256',1)
            s=change(s,'uint8_t zx,uint8_t zy){','uint8_t zx,uint8_t zy,unsigned kernel){',1)
            s=change(s,'c->dw_valid=0;\n for(unsigned i=0;i<c->k;',
                     'c->dw_valid=0;\n if(kernel<11 || kernel>21 || !(kernel&1))return -EINVAL;\n for(unsigned i=0;i<c->k;',1)
            s=change(s,'header(c->tx,10,c->k,11,c->tag)','header(c->tx,13,c->k,kernel,c->tag)',1)
            s=change(s,'uint8_t *p=c->tx+16+i*16;memcpy(p,w+i*11,11);memset(p+11,0,5);',
                     'uint8_t *p=c->tx+16+i*32;memcpy(p,w+i*kernel,kernel);memset(p+kernel,0,32-kernel);',1)
            s=change(s,'p=c->tx+16+c->k*16+i*16;','p=c->tx+16+c->k*32+i*16;',1)
            s=change(s,'transact(c,16+c->k*32,16,1,0)','transact(c,16+c->k*48,16,1,0)',1)
            s=change(s,'ack(c,c->rx,c->k,11,c->tag)','ack(c,c->rx,c->k,kernel,c->tag)',1)
        elif name=='graph.py':
            s=change(s,'wd.shape[1:] == (1,11)',
                     'wd.shape[1] == 1 and wd.shape[2] in (11,13,15,17,19,21)',1)
            s=change(s,"wd.shape[0] <= 1024 and wp.shape[0] <= 1024","wd.shape[0] == 256 and wp.shape[0] == 256",1)
            s=change(s,"da.get('pads') == [5,5]","da.get('pads') == [wd.shape[2]//2]*2",1)
            start=s.index('    for index in (0,5,10,15):')
            end=s.index('    for n in g.graph.node:',start)
            s=s[:start]+'''    selected=[]
    for block in range(1,13):
        for index in (0,5,10,15,20):
            dw=f'/encoder/encoder.{block}/mconv.{index}/conv/Conv_quant'
            pw=f'/encoder/encoder.{block}/mconv.{index+1}/conv/Conv_quant'
            if dw not in names or pw not in names or replaced==32:continue
            try:next_graph=one_pair(g,dw,pw,oracle)
            except AssertionError:continue
            g=next_graph;replaced+=1;selected.append((dw,pw))
    assert replaced in (1,32), f'Expected 32 model pairs or one extracted pair, got {replaced}'
''' + s[end:]
        elif name=='smoke.py':
            s=change(s,'for c,m,t,valid,zx,dzy,pzy in','for c,m,t,valid,zx,dzy,pzy in',1)
            # Each isolated shape is exercised at every supported kernel length.
            start=s.index('    for c,m,t,valid,zx,dzy,pzy in')
            end=s.index('    write_json(a.out',start)
            section=s[start:end]
            section=change(section,'(c,1,11)','(c,1,kernel)',1)
            section=change(section,'pads=[5,5]','pads=[kernel//2]*2',1)
            section=change(section,"'valid_times':valid,'backend':kind","'valid_times':valid,'kernel':kernel,'backend':kind",1)
            s=s[:start]+'    for kernel in (11,13,15,17,19,21):\n'+''.join('    '+line+'\n' for line in section.splitlines())+s[end:]
        elif name in ('benchmark.py','benchmark_block.py'):
            if name=='benchmark.py':
                s=change(s,"(4 if kind=='fpga' else 0)","(32 if kind=='fpga' else 0)",1)
                s=change(s,"(4 if kind=='oracle' else 0)","(32 if kind=='oracle' else 0)",1)
                s=change(s,"['ioctls']==4","['ioctls']==32",1)
                s=change(s,"'runtime':'cache'","'runtime':'shortcache'",1)
            s=s.replace("'reports/fused/cache_","'reports/fused/shortcache_")
        elif name=='run_latency_checks.py':
            s=s.replace('cache_irq_restoration','shortcache_irq_restoration').replace("f'reports/fused/cache_","f'reports/fused/shortcache_")
        write(dst/name,s)

def rtl():
    src=ROOT/'rtl/experimental'
    s=(src/'qn_pair_cache_core.v').read_text()
    s=change(s,'qn_pair_cache_core','qn_short_cache_core',1)
    s=change(s,'[1:0] cache_select','[4:0] cache_select',1)
    s=change(s,'[3:0] slot_valid,slot_quant','[31:0] slot_valid,slot_quant',1)
    s=change(s,'[0:3]','[0:31]')
    s=change(s,'reset_slot<4','reset_slot<32',1)
    s=change(s,'KW+GW+1:0','KW+GW+4:0')
    s=change(s,'KW+GW+2','KW+GW+5')
    s=change(s,'params[0:4*','params[0:32*',1)
    s=change(s,'(* ram_style="distributed" *) reg [77:0] params','(* ram_style="block" *) reg [77:0] params',1)
    s=change(s,'  assign qb[lane*32+:32]=params[{cache_select,selected_group}][31:0];',
             '  reg [77:0] current_params;\n  always @(posedge aclk) current_params<=params[{cache_select,selected_group}];\n  assign qb[lane*32+:32]=current_params[31:0];',1)
    s=s.replace('params[{cache_select,selected_group}]','current_params')
    s=s.replace('current_params<=current_params','current_params<=params[{cache_select,selected_group}]')
    s=change(s,'.MEMORY_SIZE(65536*128),.MEMORY_PRIMITIVE("ultra")',
             '.MEMORY_SIZE(4096*128),.MEMORY_PRIMITIVE("block")',1)
    s=change(s,'.ADDR_WIDTH_A(16)','.ADDR_WIDTH_A(12)',1)
    s=change(s,'.ADDR_WIDTH_B(16)','.ADDR_WIDTH_B(12)',1)
    s=change(s,'write_beat[15:0]','write_beat[11:0]',1)
    s=change(s,'read_address[15:0]','read_address[11:0]',1)
    s=change(s,'ht>4096','ht>256',1)
    s=change(s,'hbeats>65536','hbeats>4096',1)
    write(src/'qn_short_cache_core.v',s)
    s=(src/'qn_pair_cache_axis.sv').read_text()
    s=change(s,'COREHEADER=10;','COREHEADER=10,FETCH=11;',1)
    s=change(s,'[3:0] slot_dw_valid','[31:0] slot_dw_valid',1)
    s=change(s,'[0:3]','[0:31]')
    s=change(s,'reg [1:0] slot;wire [1:0] header_slot=s_axis_tdata[41:40];',
             'reg [4:0] slot;wire [4:0] header_slot=s_axis_tdata[44:40];\n reg [4:0] slot_kernel[0:31];reg [4:0] kernel;reg weight_half;reg [127:0] weight_low;',1)
    s=change(s,'wire [1:0] core_slot','wire [4:0] core_slot',1)
    s=change(s,'s_axis_tdata[47:42]==0','s_axis_tdata[47:45]==0')
    s=change(s,'hm==11','(hm>=11 && hm<=21 && hm[0])',1)
    s=change(s,'ht<=4096','ht<=256',1)
    s=change(s,'<=65536','<=4096',1)
    s=change(s,'op==9','op==12')
    s=change(s,'op==10','op==13')
    s=change(s,'op==11','op==14')
    s=change(s,'reg [87:0] dw_weights[0:1023]','reg [167:0] dw_weights[0:8191]',1)
    s=change(s,'reg [109:0] dw_params[0:1023]','reg [109:0] dw_params[0:8191]',1)
    s=change(s,'ram_style="distributed"','ram_style="block"')
    s=change(s,'wire [109:0] params=dw_params[{slot,channel[7:0]}];',
             'reg [109:0] params;reg [167:0] current_weights;\n always @(posedge aclk)begin params<=dw_params[{slot,channel[7:0]}];current_weights<=dw_weights[{slot,channel[7:0]}];end',1)
    s=change(s,'state==CONFIG || state==CHANNEL','state==FETCH || state==CONFIG || state==CHANNEL',1)
    s=change(s,'qn_pair_cache_core','qn_short_cache_core',1)
    s=change(s,'#(.MAX_KERNEL(11))','#(.MAX_T(256),.MAX_KERNEL(21))',1)
    s=change(s,".cfg_kernel(7'd11),.cfg_weights(dw_weights[{slot,channel[7:0]}])",
             '.cfg_kernel({2\'b0,slot_kernel[slot]}),.cfg_weights(current_weights)',1)
    s=change(s,'reset_slot<4','reset_slot<32',1)
    s=change(s,'pair_cycles<=0;cycles_snapshot<=0;done<=0;',
             'pair_cycles<=0;cycles_snapshot<=0;done<=0;kernel<=0;weight_half<=0;weight_low<=0;\n   for(integer r=0;r<32;r=r+1)slot_kernel[r]<=0;',1)
    s=change(s,'if(dw_header_valid)state<=DWWEIGHTS;',
             'if(dw_header_valid)begin kernel<=hm[4:0];weight_half<=0;state<=DWWEIGHTS;end',1)
    start=s.index('    DWWEIGHTS:if(accept)begin')
    end=s.index('    DWPARAMS:',start)
    s=s[:start]+'''    DWWEIGHTS:if(accept)begin
     if(!weight_half)begin
      weight_low<=s_axis_tdata;weight_half<=1;
      for(integer b=0;b<16;b=b+1)if(b>=kernel && s_axis_tdata[b*8+:8]!=0)begin status<=2;local_error<=1;state<=s_axis_tlast?ACK:DRAIN;end
      if(s_axis_tlast)begin status<=2;local_error<=1;state<=ACK;end
     end else begin
      dw_weights[{slot,channel[7:0]}]<={s_axis_tdata[39:0],weight_low};weight_half<=0;
      if(channel==channels-1)begin channel<=0;state<=DWPARAMS;end
      else channel<=channel+1;
      for(integer b=0;b<16;b=b+1)if(b+16>=kernel && s_axis_tdata[b*8+:8]!=0)begin status<=2;local_error<=1;state<=s_axis_tlast?ACK:DRAIN;end
      if(s_axis_tlast)begin status<=2;local_error<=1;state<=ACK;end
     end
    end
''' + s[end:]
    s=change(s,'slot_dw_tag[slot]<=tag;slot_dw_valid[slot]<=1;',
             'slot_dw_tag[slot]<=tag;slot_dw_valid[slot]<=1;slot_kernel[slot]<=kernel;',1)
    s=change(s,'COREHEADER:if(cs_ready)state<=CONFIG;',
             'COREHEADER:if(cs_ready)state<=FETCH;\n    FETCH:state<=CONFIG;',1)
    s=change(s,'channel<=channel+1;state<=CONFIG','channel<=channel+1;state<=FETCH',1)
    write(src/'qn_short_cache_axis.sv',s)

def driver():
    src=ROOT/'deployment/experimental-cache';dst=ROOT/'deployment/experimental-shortcache'
    for name in ('Makefile','qn_tile.c','qn_tile_uapi.h','qn_layer_protocol.h','qn_cache_protocol.h'):
        s=(src/name).read_text()
        if name=='qn_tile.c':
            s=s.replace('cache_protocol','short_cache_protocol')
            s=change(s,'slot_owner[4]','slot_owner[32]',1)
            s=change(s,'slot_tag[4]','slot_tag[32]',1)
            s=change(s,'slot_dw_valid[4]','slot_dw_valid[32]',1)
            s=s.replace('i < 4','i < 32').replace('slot < 4','slot < 32')
            s=change(s,'slot<4','slot<32',1)
            s=change(s,'layer_op!=9','layer_op!=12',1)
            s=change(s,'layer_op==9','layer_op==12')
            s=change(s,'layer_op==10','layer_op==13')
            s=change(s,'layer_op==11','layer_op==14',1)
        elif name=='qn_cache_protocol.h':
            s=change(s,'flags>3','flags>31',1)
            s=change(s,'op!=9 && op!=10 && op!=11','op!=12 && op!=13 && op!=14',1)
            s=change(s,'(get_unaligned_le32(h+4)>>16)!=(op==10?11:256)',
                     '(op!=13 && (get_unaligned_le32(h+4)>>16)!=256)',1)
            s=change(s,'op==9?4:op==10?7:8','op==12?4:op==13?7:8',1)
        elif name=='qn_layer_protocol.h':
            s=change(s,'c->m == 11','c->m >= 11 && c->m <= 21 && (c->m & 1)',1)
            s=change(s,'16 + c->k * 32','16 + c->k * 48',1)
            s=change(s,'c->times <= 4096','c->times <= 256',1)
            s=change(s,'h + 16 + i * 16','h + 16 + i * 32',1)
            s=change(s,'h + 16 + c->k * 16 + i * 16','h + 16 + c->k * 32 + i * 16',1)
            s=change(s,'            if (w[11] || get_unaligned_le32(w + 12) ||',
                     '            for (__u32 b = c->m; b < 32; ++b) if (w[b]) return -EINVAL;\n            if (',1)
        write(dst/name,s)
    # The driver include was renamed along with its readonly protocol parameter.
    p=dst/'qn_tile.c';s=p.read_text().replace('qn_short_cache_protocol.h','qn_cache_protocol.h');write(p,s)

if __name__=='__main__':
    native();rtl();driver()
    print('Generated isolated 32-slot short-window sources; validated four-slot sources preserved')
