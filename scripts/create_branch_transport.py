"""Prepare isolated protocol-18 transport and driver; retain passing oracle sources."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'deployment/experimental-stream-registered';driver=ROOT/'deployment/experimental-stream-branch'
native_source=ROOT/'software/ort_fpga_stream_branch';native=ROOT/'software/ort_fpga_stream_branch_transport'
assert not driver.exists() and not native.exists(),'Refusing to overwrite transport work'
driver.mkdir();native.mkdir()
for src,dst in ((source,driver),(native_source,native)):
    for p in src.iterdir():
        if p.is_file() and (p.suffix in ('.c','.cc','.h','.py','.sh') or p.name=='Makefile'):shutil.copy2(p,dst/p.name)
shutil.copytree(native_source/'include',native/'include')
def edit(path,replacements):
    text=path.read_text()
    for old,new in replacements:
        assert old in text,(path,old)
        text=text.replace(old,new)
    path.write_text(text)
edit(driver/'qn_cache_protocol.h',[
    ('__u32 t,n,i,j,k,offset;','__u32 t,n,i,j,k,offset,op;\n if(input_bytes<48)return -EINVAL;\n op=get_unaligned_le32(h+4)&255;'),
    ('get_unaligned_le32(h+4)!=(17U|(256U<<16))', '(op!=17 && op!=18) || get_unaligned_le32(h+4)!=(op|(256U<<16))'),
    ('!n || n>8 ||','!n || n>8 || (op==18 && n<2) ||'),
    ('output_bytes!=32+((t+15)/16)*16*256','output_bytes!=(op==18?48+2*((t+15)/16)*16*256:32+((t+15)/16)*16*256)'),
    ('c->op=17;','c->op=op;')])
edit(driver/'qn_stream_registered.h',[
    ('r->output_bytes!=r->input_bytes+32','(r->output_bytes!=r->input_bytes+32 && r->output_bytes!=2*r->input_bytes+48)')])
edit(driver/'qn_tile.c',[
    ('u32 bytes, capacity, stages, tag, header_bytes, tail_offset;', 'u32 bytes, capacity, stages, tag, header_bytes, tail_offset, op;'),
    ('static unsigned int registered_stream_protocol = 1;', 'static unsigned int residual_branch_protocol = 1;\nmodule_param(residual_branch_protocol, uint, 0444);\nstatic unsigned int registered_stream_protocol = 1;'),
    ('ret=qn_cache_validate(p->data,r.prefix_bytes+4096,4128,&command);', 'ret=qn_cache_validate(p->data,r.prefix_bytes+4096,\n        ((get_unaligned_le32((u8*)p->data+4)&255)==18)?8240:4128,&command);'),
    ('p->bytes=r.prefix_bytes;p->stages=n;p->tag=command.tag;', 'p->bytes=r.prefix_bytes;p->stages=n;p->tag=command.tag;p->op=command.op;'),
    ('if(!program){ret=-ESTALE;goto unlock;}', 'if(!program){ret=-ESTALE;goto unlock;}\n        if(stream.output_bytes!=(program->op==18?2*stream.input_bytes+48:stream.input_bytes+32)){ret=-EINVAL;goto unlock;}'),
    ('layer_op=17;layer_k=layer_m=256;', 'layer_op=program->op;layer_k=layer_m=256;'),
    ('layer_op!=17 && layer_op!=12', 'layer_op!=17 && layer_op!=18 && layer_op!=12'),
    ('\t\t}\n        if(layer_op==13)', '\t\t}\n        if(layer_op==18){\n            u8 *second=(u8*)q->output+(rx_stride-16)/2;\n            if(get_unaligned_le32(second)!=QN_LAYER_RESPONSE_MAGIC || get_unaligned_le32(second+4) ||\n               get_unaligned_le32(second+8)!=(256|(256U<<16)) || get_unaligned_le32(second+12)!=layer_tag){ret=-EPROTO;goto recover_completed;}\n        }\n        if(layer_op==13)')])
edit(driver/'test_stream_protocol.c',[
    ('for(unsigned n=1;n<=8;n++)', 'for(unsigned op=17;op<=18;op++)for(unsigned n=op==18?2:1;n<=8;n++)'),
    ('unsigned rx=32+((t+15)/16)*16*256;', 'unsigned rx=op==18?48+2*((t+15)/16)*16*256:32+((t+15)/16)*16*256;'),
    ('put(p+4,17|(256<<16))','put(p+4,op|(256<<16))'),('c.op==17','c.op==op')])
# Keep this clone physically disabled until packet tests and FPGA qualification.
# Its new low-level APIs can already be exercised through explicit mock callbacks.
edit(native/'qnc_transport.c',[
    ('const uint8_t *x,size_t t,size_t valid_t,uint8_t *y){\n if(!c || !prefix',
     'const uint8_t *x,size_t t,size_t valid_t,uint8_t *y,uint8_t *residual,unsigned stride){\n if(!c || !prefix'),
    ('if(prefix_bytes!=expected || get32(prefix)!=CMD || get32(prefix+4)!=(17|(256<<16)) || get32(prefix+12)!=tag)return -EINVAL;',
     'if(prefix_bytes<32)return -EINVAL;\n unsigned op=get32(prefix+4)&255;\n if((op!=17&&op!=18)||(op==18&&(!residual||n<2||(stride!=1&&stride!=2))) || (op==17&&residual) ||\n    prefix_bytes!=expected || get32(prefix)!=CMD || get32(prefix+4)!=(op|(256<<16)) || get32(prefix+12)!=tag)return -EINVAL;'),
    ('unsigned ib=(unsigned)prefix_bytes+256*padded,rb=32+tiles*16*256;',
     'unsigned ib=(unsigned)prefix_bytes+256*padded,rb=op==18?48+2*tiles*16*256:32+tiles*16*256;'),
    ('if(issues!=n*tiles*8*256 || active<issues)', 'if(issues!=n*tiles*4*256 || active<issues)'),
    ('const uint8_t *src=c->rx+16+((size_t)tile*16+group)*256;',
     'const uint8_t *src=c->rx+(op==18?32+256*padded:16)+((size_t)tile*16+group)*256;'),
    ('return run_stream(c,prefix,NULL,0,prefix_bytes,n,tag,x,t,valid_t,y);',
     'return run_stream(c,prefix,NULL,0,prefix_bytes,n,tag,x,t,valid_t,y,NULL,1);'),
    ('return run_stream(c,packet,packet,capacity,prefix_bytes,n,tag,x,t,valid_t,y);',
     'return run_stream(c,packet,packet,capacity,prefix_bytes,n,tag,x,t,valid_t,y,NULL,1);')])
path=native/'qnc_transport.c';text=path.read_text()
needle=' const uint8_t *counter=c->rx+rb-16;uint32_t issues=get32(counter),active=get32(counter+12);'
assert text.count(needle)==1
text=text.replace(needle, ' if(op==18){rc=ack(c,c->rx+16+256*padded,256,256,tag);if(rc)return rc;}\n'+needle)
needle=' c->profile.unpack_seconds+=now()-start;c->stats.runs+=tiles*n;c->stats.loads+=2*n;'
assert text.count(needle)==1
text=text.replace(needle,''' if(op==18){
  size_t rt=(t+stride-1)/stride;
  for(unsigned channel=0;channel<256;channel++)for(unsigned p=0;p<rt;p++){
   unsigned time=p*stride,tile=time/16,row=time%16,group=channel/16,lane=channel%16;
   residual[(size_t)channel*rt+p]=c->rx[16+((size_t)tile*16+group)*256+row*16+lane];
  }
 }
'''+needle)
text += '''
int qnc_run_branch_reuse(qnc *c,uint8_t *packet,size_t prefix_bytes,size_t capacity,unsigned n,unsigned tag,
 const uint8_t *x,size_t t,size_t valid_t,uint8_t *y,uint8_t *residual,unsigned stride){
 return run_stream(c,packet,packet,capacity,prefix_bytes,n,tag,x,t,valid_t,y,residual,stride);
}
int qnc_run_branch_registered(qnc *c,uint64_t handle,uint8_t *packet,size_t prefix_bytes,size_t capacity,unsigned n,unsigned tag,
 const uint8_t *x,size_t t,size_t valid_t,uint8_t *y,uint8_t *residual,unsigned stride){
 if(!c || c->fd<0 || !handle || c->registered_handle)return -EINVAL;
 c->registered_handle=handle;c->registered_prefix_bytes=prefix_bytes;
 int rc=qnc_run_branch_reuse(c,packet,prefix_bytes,capacity,n,tag,x,t,valid_t,y,residual,stride);
 c->registered_handle=0;c->registered_prefix_bytes=0;return rc;
}
'''
path.write_text(text)
path=native/'qnc.h';text=path.read_text();position=text.rindex('#endif')
text=text[:position]+'''int qnc_run_branch_reuse(qnc*,uint8_t*,size_t,size_t,unsigned,unsigned,const uint8_t*,size_t,size_t,uint8_t*,uint8_t*,unsigned);
int qnc_run_branch_registered(qnc*,uint64_t,uint8_t*,size_t,size_t,unsigned,unsigned,const uint8_t*,size_t,size_t,uint8_t*,uint8_t*,unsigned);
'''+text[position:];path.write_text(text)
print('Prepared isolated branch driver and low-level transport; native physical branch remains disabled pending qualification')
