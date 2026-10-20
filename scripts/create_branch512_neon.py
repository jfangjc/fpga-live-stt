"""Isolate transport-only vector unpacking; preserve the qualified backend."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'software/ort_fpga_stream_branch512'
dest=ROOT/'software/ort_fpga_stream_branch512_neon'
dest.mkdir(exist_ok=True);(dest/'include').mkdir(exist_ok=True)
def save(path,data):
    if path.exists():assert path.read_bytes()==data,path
    else:path.write_bytes(data)
for p in list(source.glob('*'))+list((source/'include').glob('*')):
    if p.is_file() and p.suffix in ('.cc','.h','.py','.sh'):
        save(dest/p.relative_to(source),p.read_bytes())
text=(source/'qnc_transport.c').read_text()
start=text.index('static void output16_u8(');end=text.index('\n}\n#endif',start)+2
helper=text[start:end].replace('static void output16_u8(', 'static void output_partial_u8(')
helper=helper.replace('size_t stride,unsigned lanes)', 'size_t stride,unsigned times,unsigned lanes,unsigned step)')
old=' for(unsigned i=0;i<lanes;i++)vst1q_u8(dst+i*stride,row[i]);'
new=''' for(unsigned i=0;i<lanes;i++) {
  uint8x16_t v=step==2?vuzp1q_u8(row[i],row[i]):row[i];
  uint8_t *out=dst+i*stride;
  if(times==16)vst1q_u8(out,v);
  else if(times==8)vst1_u8(out,vget_low_u8(v));
  else if(times==4){uint32_t word=vgetq_lane_u32(vreinterpretq_u32_u8(v),0);memcpy(out,&word,4);}
  else if(times==2){uint16_t word=vgetq_lane_u16(vreinterpretq_u16_u8(v),0);memcpy(out,&word,2);}
  else if(times==1)*out=vgetq_lane_u8(v,0);
  else {uint8_t bytes[16];vst1q_u8(bytes,v);memcpy(out,bytes,times);}
 }'''
assert old in helper;helper=helper.replace(old,new)
text=text[:end]+'\n'+helper+text[end:]
a=text.index('static int run_stream(');b=text.index('\nint qnc_run_stream(',a)
run=text[a:b]
run=run.replace('if(nt==16){output16_u8(src,y+(size_t)group*16*t+offset,t,16);continue;}',
               'output_partial_u8(src,y+(size_t)group*16*t+offset,t,nt,16,1);continue;')
old='''  for(unsigned channel=0;channel<256;channel++)for(unsigned p=0;p<rt;p++){
   unsigned time=p*stride,tile=time/16,row=time%16,group=channel/16,lane=channel%16;
   residual[(size_t)channel*rt+p]=c->rx[16+((size_t)tile*16+group)*256+row*16+lane];
  }'''
new='''#ifdef QNC_NEON
  for(unsigned tile=0;tile<tiles;tile++)for(unsigned group=0;group<16;group++){
   unsigned offset=tile*16,nt=t-offset<16?(unsigned)(t-offset):16;
   const uint8_t *src=c->rx+16+((size_t)tile*16+group)*256;
   output_partial_u8(src,residual+(size_t)group*16*rt+offset/stride,rt,(nt+stride-1)/stride,16,stride);
  }
#else
'''+old+'''
#endif'''
assert old in run;run=run.replace(old,new)
text=text[:a]+run+text[b:]
text+='''
int qnc_output_neon_enabled(void){
#ifdef QNC_NEON
 return 1;
#else
 return 0;
#endif
}
'''
save(dest/'qnc_transport.c',text.encode())
print('Prepared isolated NEON short-tile and stride-two residual unpacking')
