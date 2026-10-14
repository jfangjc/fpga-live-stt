"""Generate an independent shared library from the existing C API scaffold."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'software/latency/boundary_lut.cc').read_text()
start=text.index('struct Kernel {');end=text.index('OrtCustomOp op={};')
kernel=r'''struct Kernel {
    float residual_scale,output_scale;uint8_t residual_zero,output_zero;bool relu;
    explicit Kernel(const OrtKernelInfo* info){
        int64_t flag=0;check(api->KernelInfoGetAttribute_int64(info,"relu",&flag));relu=flag!=0;
        for(size_t i=4;i<8;i++){
            int constant=0;const OrtValue* value=nullptr;
            check(api->KernelInfoGetConstantInput_tensor(info,i,&constant,&value));
            if(!constant || !shape(value).empty())throw std::runtime_error("Residual scales/zeros must be scalar constants");
            if(i==4)residual_scale=*data<float>(value);
            if(i==5)residual_zero=*data<uint8_t>(value);
            if(i==6)output_scale=*data<float>(value);
            if(i==7)output_zero=*data<uint8_t>(value);
        }
        if(!(residual_scale>0 && output_scale>0))throw std::runtime_error("Invalid residual scales");
    }
    void compute(OrtKernelContext* context){
        const OrtValue* values[4];for(size_t i=0;i<4;i++)check(api->KernelContext_GetInput(context,i,&values[i]));
        auto dims=shape(values[0]);
        if(dims.size()!=3 || dims[0]!=1 || dims[1]<=0 || dims[2]<=0 || shape(values[2])!=dims ||
            shape(values[1])!=std::vector<int64_t>{1,dims[1],1})throw std::runtime_error("Invalid residual broadcast");
        auto md=shape(values[3]);if(md!=std::vector<int64_t>{1,1,1} && md!=std::vector<int64_t>{1,1,dims[2]})
            throw std::runtime_error("Invalid residual mask");
        auto x=data<float>(values[0]),gate=data<float>(values[1]);auto res=data<uint8_t>(values[2]);auto mask=data<bool>(values[3]);
        OrtValue* output=nullptr;check(api->KernelContext_GetOutput(context,0,dims.data(),dims.size(),&output));
        void* pointer=nullptr;check(api->GetTensorMutableData(output,&pointer));auto y=static_cast<uint8_t*>(pointer);
        size_t times=dims[2];
        for(size_t c=0;c<static_cast<size_t>(dims[1]);c++){
            size_t offset=c*times,t=0;
#if defined(__aarch64__) && defined(__ARM_NEON)
            auto scale=vdupq_n_f32(residual_scale),outscale=vdupq_n_f32(output_scale),g=vdupq_n_f32(gate[c]);
            auto minimum=vdupq_n_f32(-static_cast<float>(output_zero)),maximum=vdupq_n_f32(255.f-output_zero);
            auto zero=vdupq_n_f32(0);auto z=vdupq_n_s32(output_zero);
            for(;t+4<=times;t+=4){
                uint32_t packed;std::memcpy(&packed,res+offset+t,4);
                auto bytes=vreinterpret_u8_u32(vdup_n_u32(packed));
                auto integers=vreinterpretq_s32_u32(vmovl_u16(vget_low_u16(vmovl_u8(bytes))));
                auto r=vmulq_f32(vcvtq_f32_s32(vsubq_s32(integers,vdupq_n_s32(residual_zero))),scale);
                // Separate rounded multiply and add, matching original ORT nodes.
                auto result=vaddq_f32(vmulq_f32(vld1q_f32(x+offset+t),g),r);
                if(relu)result=vmaxq_f32(result,zero);
                uint32_t m[4];for(size_t i=0;i<4;i++)m[i]=mask[md[2]==1?0:t+i]?0xffffffffu:0;
                result=vbslq_f32(vld1q_u32(m),zero,result);
                result=vminnmq_f32(vmaxnmq_f32(vdivq_f32(result,outscale),minimum),maximum);
                auto q=vaddq_s32(vcvtnq_s32_f32(result),z);
                auto words=vqmovun_s32(q);auto out=vqmovn_u16(vcombine_u16(words,words));
                uint32_t final=vget_lane_u32(vreinterpret_u32_u8(out),0);std::memcpy(y+offset+t,&final,4);
            }
#endif
            for(;t<times;t++){
                float r=(static_cast<int>(res[offset+t])-residual_zero)*residual_scale;
                float value=x[offset+t]*gate[c];value=value+r;
                if(relu)value=std::max(value,0.f);
                if(mask[md[2]==1?0:t])value=0;
                value=std::fmin(std::fmax(value/output_scale,-static_cast<float>(output_zero)),255.f-output_zero);
                y[offset+t]=static_cast<uint8_t>(static_cast<int>(std::nearbyint(value))+output_zero);
            }
        }
    }
};
'''
text=text[:start]+kernel+text[end:]
text=text.replace('#include <vector>','#include <vector>\n#include <cmath>')
text=text.replace('return "LookupMask"','return "ResidualTail"').replace('return 3;','return 8;')
text=text.replace('return i==1?ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL:ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8;',
                  'return i==3?ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL:(i==0 || i==1 || i==4 || i==6)?ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT:ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8;')
text=text.replace('prototype.cpu.boundary','prototype.cpu.residual')
(ROOT/'software/latency/residual_tail.cc').write_text(text)
print('Generated separate residual tail C API library source')
