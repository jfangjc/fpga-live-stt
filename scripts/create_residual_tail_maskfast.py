"""Keep original divisions/partial lanes; skip mask work for all-valid inputs."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'software/latency/residual_tail.cc').read_text()
source=source.replace('        size_t times=dims[2];','''        size_t times=dims[2];
        bool any_mask=false;
        for(size_t i=0;i<static_cast<size_t>(md[2]);i++)any_mask=any_mask || mask[i];
        if(md[2]==1 && mask[0]){
            std::memset(y,output_zero,static_cast<size_t>(dims[1])*times);return;
        }''')
source=source.replace('                uint32_t m[4];for(size_t i=0;i<4;i++)m[i]=mask[md[2]==1?0:t+i]?0xffffffffu:0;\n                result=vbslq_f32(vld1q_u32(m),zero,result);', '''                if(any_mask){
                    uint32_t m[4];for(size_t i=0;i<4;i++)m[i]=mask[md[2]==1?0:t+i]?0xffffffffu:0;
                    result=vbslq_f32(vld1q_u32(m),zero,result);
                }''')
source=source.replace('if(mask[md[2]==1?0:t])value=0;', 'if(any_mask && mask[md[2]==1?0:t])value=0;')
source+='''
extern "C" int residual_tail_maskfast_enabled(){
#if defined(__aarch64__) && defined(__ARM_NEON)
 return 1;
#else
 return 0;
#endif
}
'''
dest=ROOT/'software/latency/residual_tail_maskfast.cc'
if dest.exists():assert dest.read_text()==source
else:dest.write_text(source,newline='\n')
test=(ROOT/'software/latency/test_residual_tail_vector.py').read_text().replace('residual_tail_vector','residual_tail_maskfast')
dest=ROOT/'software/latency/test_residual_tail_maskfast.py'
if dest.exists():assert dest.read_text()==test
else:dest.write_text(test,newline='\n')
bench=(ROOT/'software/latency/benchmark_residual_tail_vector.py').read_text().replace('residual_tail_vector','residual_tail_maskfast')
bench=bench.replace('mask=np.zeros((1,1,times),np.bool_);mask[:,:,max(1,times*3//4):]=True', "mask=np.zeros((1,1,times),np.bool_) # All-valid hot path; masked parity is tested separately.")
bench=bench.replace("'channels':channels,'bit_exact':True", "'channels':channels,'mask':'all_valid','bit_exact':True")
dest=ROOT/'software/latency/benchmark_residual_tail_maskfast.py'
if dest.exists():assert dest.read_text()==bench
else:dest.write_text(bench,newline='\n')
print('Prepared isolated all-valid mask fast path with unchanged arithmetic')
