"""Add a prepacked streamed physical transport; preserve original reference files."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];path=ROOT/'software/ort_fpga_stream_exact/pointwise.cc'
text=path.read_text()
assert 'Streamed FPGA backend is not implemented/qualified yet' in text
text=text.replace('bool emulate;std::vector<Stage> stages;', 'bool emulate;std::vector<Stage> stages;std::vector<uint8_t> prefix;uint32_t outer_tag=1;')
needle='  require(p==end,"Trailing chain program bytes");'
replacement=needle+r'''
  if(!emulate){
   const auto* raw=data<uint8_t>(value);uint32_t hash=2166136261u;
   for(size_t i=0;i<elements(value);i++){hash^=raw[i];hash*=16777619u;}
   outer_tag=hash?hash:1;
   prefix.resize(32+count*16+count*86016+(count-1)*256,0);
   auto put=[&](size_t offset,uint32_t word){for(unsigned b=0;b<4;b++)prefix[offset+b]=uint8_t(word>>(8*b));};
   put(0,0x32434e51);put(4,17|(256u<<16));put(8,256);put(12,outer_tag);put(16,count<<16);
   for(unsigned i=0;i<count;i++){
    auto& s=stages[i];uint32_t tag=outer_tag+i*0x9e3779b9u;if(!tag)tag=1;
    put(32+i*16,i|(uint32_t(s.masked)<<8)|(uint32_t(s.dw.width)<<16));put(36+i*16,tag);
    size_t base=32+count*16+i*86016;
    for(unsigned g=0;g<16;g++)for(unsigned k=0;k<256;k++)for(unsigned lane=0;lane<16;lane++)
     prefix[base+(g*256+k)*16+lane]=uint8_t(s.pw.w[(g*16+lane)*256+k]);
    for(unsigned c=0;c<256;c++){
     size_t pw=base+65536+c*16;
     put(pw,uint32_t(s.corrections[c]));put(pw+4,uint32_t(s.pw.mult[c]));put(pw+8,s.pw.shifts[c]|(uint32_t(s.pw.zy)<<8));
     std::memcpy(prefix.data()+base+69632+c*48,s.dw.w.data()+c*s.dw.width,size_t(s.dw.width));
     size_t dp=base+69632+12288+c*16;
     put(dp,uint32_t(s.dw.bias[c]));put(dp+4,uint32_t(s.dw.mult[c]));put(dp+8,s.dw.shifts[c]|(uint32_t(s.dw.zy)<<8));put(dp+12,s.dw.zx);
    }
    if(i+1<count)std::memcpy(prefix.data()+32+count*16+count*86016+i*256,s.lookup,256);
   }
  }
'''
text=text.replace(needle,replacement)
text=text.replace('   throw std::runtime_error("Streamed FPGA backend is not implemented/qualified yet");',r'''
   if(!device){
    std::ifstream version("/sys/module/qn_tile/parameters/stream_chain_protocol");unsigned protocol=0;
    require(bool(version>>protocol)&&protocol==1,"Matching exact streamed-block driver required");
    device=qnc_open("/dev/qn-tile");require(device,"Cannot open physical streamed FPGA");
   }
   int rc=qnc_run_stream(device,prefix.data(),prefix.size(),unsigned(stages.size()),outer_tag,x,t,valid_t,y);
   if(rc)throw std::runtime_error("Streamed FPGA transport failed: "+std::to_string(rc));
   physical_calls+=stages.size();''')
path.write_bytes(text.encode())
print('Physical stream implementation added; matching driver/image qualification is still required')
