"""Isolate reciprocal quantization; require all finite-float byte boundaries."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'software/latency/residual_tail_maskfast.cc').read_text()
helper='''#if defined(__aarch64__) && defined(__ARM_NEON)
float32x4_t reciprocal_quotient(float32x4_t value,double inverse){
    auto inv=vdupq_n_f64(inverse);
    auto low=vmulq_f64(vcvt_f64_f32(vget_low_f32(value)),inv);
    auto high=vmulq_f64(vcvt_f64_f32(vget_high_f32(value)),inv);
    return vcombine_f32(vcvt_f32_f64(low),vcvt_f32_f64(high));
}
#endif
'''
text=text.replace('struct Kernel {',helper+'struct Kernel {')
text=text.replace('float residual_scale,output_scale;', 'double output_inverse;float residual_scale,output_scale;')
text=text.replace('throw std::runtime_error("Invalid residual scales");', 'throw std::runtime_error("Invalid residual scales");\n        output_inverse=1.0/static_cast<double>(output_scale);')
text=text.replace('vdivq_f32(result,outscale)', 'reciprocal_quotient(result,output_inverse)')
text=text.replace('value/output_scale', 'static_cast<float>(static_cast<double>(value)*output_inverse)')
text=text.replace('residual_tail_maskfast_enabled','residual_tail_recip64_enabled')
text+='''
// Proof entry points use the same quotient and byte-rounding operations.
extern "C" uint32_t residual_tail_divide_reference(float x,float scale,uint32_t zero){
    float q=x/scale;
    q=std::fmin(std::fmax(q,-float(zero)),255.f-zero);
    return uint32_t(int(std::nearbyint(q))+int(zero));
}
extern "C" uint32_t residual_tail_recip64_byte(float x,float scale,uint32_t zero){
#if defined(__aarch64__) && defined(__ARM_NEON)
    auto q=reciprocal_quotient(vdupq_n_f32(x),1.0/double(scale));
    q=vminnmq_f32(vmaxnmq_f32(q,vdupq_n_f32(-float(zero))),vdupq_n_f32(255.f-zero));
    return uint32_t(vgetq_lane_s32(vcvtnq_s32_f32(q),0)+int(zero));
#else
    float q=float(double(x)*(1.0/double(scale)));
    q=std::fmin(std::fmax(q,-float(zero)),255.f-zero);
    return uint32_t(int(std::nearbyint(q))+int(zero));
#endif
}
'''
dest=ROOT/'software/latency/residual_tail_recip64.cc'
if dest.exists():assert dest.read_text()==text
else:dest.write_text(text,newline='\n')
test=(ROOT/'software/latency/test_residual_tail_maskfast.py').read_text().replace('residual_tail_maskfast','residual_tail_recip64')
dest=ROOT/'software/latency/test_residual_tail_recip64.py'
if dest.exists():assert dest.read_text()==test
else:dest.write_text(test,newline='\n')
bench=(ROOT/'software/latency/benchmark_residual_tail_maskfast.py').read_text().replace('residual_tail_maskfast','residual_tail_recip64')
bench=bench.replace("ROOT/'software/latency/libresidual_tail.so'", "ROOT/'software/latency/libresidual_tail_maskfast.so'")
dest=ROOT/'software/latency/benchmark_residual_tail_recip64.py'
if dest.exists():assert dest.read_text()==bench
else:dest.write_text(bench,newline='\n')
print('Prepared isolated reciprocal quantizer; exhaustive byte-transition gate required')
