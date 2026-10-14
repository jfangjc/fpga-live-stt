"""Preserve qualified tail code; vectorize partial lanes and shared masks."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'software/latency/residual_tail.cc').read_text()
source=source.replace('        size_t times=dims[2];', '''        size_t times=dims[2];
#if defined(__aarch64__) && defined(__ARM_NEON)
        // Expand the shared mask once, including safe padding for partial vectors.
        std::vector<uint32_t> expanded_mask(times+3,0);
        for(size_t i=0;i<times;i++)expanded_mask[i]=mask[md[2]==1?0:i]?0xffffffffu:0;
#endif''')
source=source.replace('            for(;t+4<=times;t+=4){\n                uint32_t packed;std::memcpy(&packed,res+offset+t,4);', '''            for(;t<times;t+=4){
                const size_t lanes=std::min(size_t(4),times-t);
                uint32_t packed=0;std::memcpy(&packed,res+offset+t,lanes);
                float partial[4]={0,0,0,0};
                if(lanes!=4)std::memcpy(partial,x+offset+t,lanes*sizeof(float));
                auto xv=lanes==4?vld1q_f32(x+offset+t):vld1q_f32(partial);''')
source=source.replace('vmulq_f32(vld1q_f32(x+offset+t),g)', 'vmulq_f32(xv,g)')
source=source.replace('                uint32_t m[4];for(size_t i=0;i<4;i++)m[i]=mask[md[2]==1?0:t+i]?0xffffffffu:0;\n                result=vbslq_f32(vld1q_u32(m),zero,result);',
                      '                result=vbslq_f32(vld1q_u32(expanded_mask.data()+t),zero,result);')
source=source.replace('std::memcpy(y+offset+t,&final,4);','std::memcpy(y+offset+t,&final,lanes);')
source+='''
extern "C" int residual_tail_vector_enabled(){
#if defined(__aarch64__) && defined(__ARM_NEON)
 return 1;
#else
 return 0;
#endif
}
'''
path=ROOT/'software/latency/residual_tail_vector.cc'
if path.exists():assert path.read_text()==source
else:path.write_text(source,newline='\n')
test=(ROOT/'software/latency/test_residual_tail.py').read_text()
test=test.replace('libresidual_tail.so','libresidual_tail_vector.so').replace('residual_tail_validation.json','residual_tail_vector_validation.json').replace('residual_tail.cc','residual_tail_vector.cc')
test=test.replace('(1,3,4,17,256)', '(1,3,4,13,17,26,63,126,256)')
test=test.replace("library=ROOT/'software/latency/libresidual_tail_vector.so'", "library=ROOT/'software/latency/libresidual_tail_vector.so'\nimport ctypes\nassert ctypes.CDLL(str(library)).residual_tail_vector_enabled()==1")
path=ROOT/'software/latency/test_residual_tail_vector.py'
if path.exists():assert path.read_text()==test
else:path.write_text(test,newline='\n')
print('Prepared exact vector partial lanes and one shared mask expansion')
