// Physical QNC2 operator inside one ORT graph. There is no CPU fallback.
#include "include/onnxruntime_c_api.h"
extern "C" {
#include "qnc.h"
}
#include <algorithm>
#include <cmath>
#include <cerrno>
#include <cstring>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>
#include <fstream>
#if defined(__aarch64__)
#include <arm_neon.h>
#endif

namespace {
const OrtApi* api;
std::mutex device_mutex;
qnc* device=nullptr;
const void* resident=nullptr;
uint64_t physical_calls=0, oracle_calls=0;
void check(OrtStatus* status) {
    if (!status) return;
    std::string message=api->GetErrorMessage(status);
    api->ReleaseStatus(status); throw std::runtime_error(message);
}
std::vector<int64_t> shape(const OrtValue* value) {
    OrtTensorTypeAndShapeInfo* info=nullptr;
    check(api->GetTensorTypeAndShape(value,&info));
    size_t rank=0; auto status=api->GetDimensionsCount(info,&rank);
    if(status) {api->ReleaseTensorTypeAndShapeInfo(info);check(status);}
    std::vector<int64_t> dims(rank);
    status=api->GetDimensions(info,dims.data(),rank);
    api->ReleaseTensorTypeAndShapeInfo(info); check(status); return dims;
}
template<class T> const T* data(const OrtValue* value) {
    const void* p=nullptr;check(api->GetTensorData(value,&p));return static_cast<const T*>(p);
}
const OrtValue* input(OrtKernelContext* c,size_t i) {
    const OrtValue* v=nullptr;check(api->KernelContext_GetInput(c,i,&v));
    if(!v) throw std::runtime_error("Missing pointwise input");return v;
}
struct Kernel {
    bool emulate,quantized,prepacked;
    int64_t stride;
    std::vector<int8_t> weights, packed;
    std::vector<int32_t> sums, acc;
    std::vector<int32_t> corrections,multipliers;
    std::vector<uint8_t> shifts,quant_output,load_body;
    int64_t m=0,k=0;
    const OrtValue* weight_identity=nullptr;
    explicit Kernel(const OrtKernelInfo* info,bool oracle,bool quant,bool pack):emulate(oracle),quantized(quant),prepacked(pack) {
        check(api->KernelInfoGetAttribute_int64(info,"stride",&stride));
        if(stride!=1 && stride!=2) throw std::runtime_error("Unsupported pointwise stride");
        if(quantized && stride!=1)throw std::runtime_error("Retained-input operator requires stride one");
        for(size_t i=1;i<9;i++) {
            int constant=0;const OrtValue* value=nullptr;
            check(api->KernelInfoGetConstantInput_tensor(info,i,&constant,&value));
            if(!constant)throw std::runtime_error("Pointwise quantization/weights/bias must be constant initializers");
        }
    }
    void compute(OrtKernelContext* c) {
        const OrtValue* values[9];for(size_t i=0;i<9;++i)values[i]=input(c,i);
        auto xs=shape(values[0]), ws=shape(values[3]);
        if(xs.size()!=3 || xs[0]!=1 || ws.size()!=3 || ws[2]!=1 ||
           ws[0]<1 || ws[0]>1024 || ws[1]<1 || ws[1]>1024 || xs[1]!=ws[1] || xs[2]<1)
            throw std::runtime_error("Unsupported pointwise tensor shape");
        const int64_t t=(xs[2]+stride-1)/stride;
        if(t>1000000) throw std::runtime_error("Pointwise length exceeds checked bound");
        const float sx=*data<float>(values[1]),sy=*data<float>(values[6]);
        const uint8_t zx=*data<uint8_t>(values[2]),zy=*data<uint8_t>(values[7]);
        const float* sw=data<float>(values[4]);const int8_t* zw=data<int8_t>(values[5]);
        auto swshape=shape(values[4]),zwshape=shape(values[5]);
        size_t nsw=1,nzw=1;for(auto d:swshape)nsw*=d;for(auto d:zwshape)nzw*=d;
        if(nsw!=size_t(ws[0]) || (nzw!=1 && nzw!=size_t(ws[0])) ||
           !std::isfinite(sx) || !std::isfinite(sy) || sx<=0 || sy<=0)
            throw std::runtime_error("Invalid quantization parameters");
        for(int64_t o=0;o<ws[0];++o)
            if(zw[nzw==1?0:o]!=0 || !std::isfinite(sw[o]) || sw[o]<=0)
                throw std::runtime_error("Pointwise requires symmetric INT8 weights");
        auto bs=shape(values[8]);if(bs.size()!=1 || bs[0]!=ws[0])
            throw std::runtime_error("Invalid pointwise bias shape");
        const int32_t* bias=data<int32_t>(values[8]);
        if(weights.empty()) {
            m=ws[0];k=ws[1];
            const int8_t* w=data<int8_t>(values[3]);weights.assign(w,w+m*k);
            sums.assign(m,0);for(int64_t o=0;o<m;++o)for(int64_t j=0;j<k;++j)sums[o]+=weights[o*k+j];
        } else if(m!=ws[0] || k!=ws[1]) throw std::runtime_error("Weight dimensions changed");
        // The model builder permits initializer weights only. Each kernel owns
        // its copied weights; device residency is invalidated when another runs.
        const uint8_t* x=data<uint8_t>(values[0]);
        if(emulate || !quantized) {
            packed.resize(k*t);acc.resize(m*t);
            for(int64_t j=0;j<k;++j)for(int64_t p=0;p<t;++p)
                packed[j*t+p]=int8_t(int(x[j*xs[2]+p*stride])-128);
        }
        if(quantized && corrections.empty()) {
            corrections.resize(m);multipliers.resize(m);shifts.resize(m);
            for(int64_t o=0;o<m;o++) {
                int64_t correction=int64_t(128-int(zx))*sums[o]+bias[o];
                if(correction<INT32_MIN || correction>INT32_MAX)throw std::runtime_error("Affine correction overflow");
                corrections[o]=int32_t(correction);
                float ratio=(sx*sw[o])/sy;
                if(!std::isfinite(ratio)||ratio<=0)throw std::runtime_error("Invalid affine multiplier");
                if(ratio<=std::ldexp(1.f,-32)) {multipliers[o]=0;shifts[o]=1;}
                else {
                    int exponent;double significand=std::frexp(double(ratio),&exponent);
                    int64_t multiplier=int64_t(std::nearbyint(std::ldexp(significand,31)));
                    if(multiplier==int64_t(1)<<31) {multiplier>>=1;exponent++;}
                    int shift=31-exponent;
                    if(shift<1 || shift>62)throw std::runtime_error("Affine multiplier exceeds supported range");
                    multipliers[o]=int32_t(multiplier);shifts[o]=uint8_t(shift);
                }
            }
        }
        if(quantized && prepacked && !emulate && load_body.empty()) {
            const size_t groups=(m+15)/16,weight_bytes=groups*k*16;
            load_body.assign(weight_bytes+groups*256,0);
            for(int64_t o=0;o<m;o++)for(int64_t j=0;j<k;j++)
                load_body[(o/16*k+j)*16+o%16]=uint8_t(weights[o*k+j]);
            auto put=[](uint8_t* p,uint32_t v){for(unsigned b=0;b<4;b++)p[b]=uint8_t(v>>(8*b));};
            for(size_t o=0;o<groups*16;o++) {
                uint8_t* p=load_body.data()+weight_bytes+o*16;
                put(p,o<size_t(m)?uint32_t(corrections[o]):0);
                put(p+4,o<size_t(m)?uint32_t(multipliers[o]):0);
                put(p+8,o<size_t(m)?uint32_t(shifts[o])|(uint32_t(zy)<<8):1);
            }
        }
        void* physical_ptr=nullptr;
        if(quantized && !emulate) {
            int64_t dims[3]={1,m,t};OrtValue* out=nullptr;
            check(api->KernelContext_GetOutput(c,0,dims,3,&out));
            check(api->GetTensorMutableData(out,&physical_ptr));
        }
        {
            std::lock_guard<std::mutex> lock(device_mutex);
            if(emulate) {
                ++oracle_calls;
                for(int64_t o=0;o<m;++o)for(int64_t p=0;p<t;++p) {
                    int32_t sum=0;for(int64_t j=0;j<k;++j)sum+=int32_t(weights[o*k+j])*packed[j*t+p];
                    acc[o*t+p]=sum;
                }
            } else {
                if(!device) {
                    std::ifstream capacity("/sys/module/qn_tile/parameters/rx_capacity");unsigned size=0;
                    if(!(capacity>>size) || size!=4u*1024u*1024u)
                        throw std::runtime_error("Matching experimental 4 MiB receive-buffer driver is required");
                    if(quantized) {
                        std::ifstream version("/sys/module/qn_tile/parameters/quant_protocol");unsigned protocol=0;
                        if(!(version>>protocol)||protocol!=1)throw std::runtime_error("Matching fused quantized-output driver is required");
                        std::ifstream bulk_version("/sys/module/qn_tile/parameters/bulk_protocol");unsigned bulk=0;
                        if(!(bulk_version>>bulk)||bulk!=1)throw std::runtime_error("Matching retained-input driver is required");
                    }
                    device=qnc_open("/dev/qn-tile");if(!device)throw std::runtime_error("Cannot open FPGA device: "+std::string(strerror(errno)));
                }
                int rc=0;
                if(resident!=this) {
                    resident=nullptr;
                    rc=quantized ? (prepacked ? qnc_load_quant_packet(device,load_body.data(),load_body.size(),m,k) : qnc_load_quant(device,weights.data(),m,k,corrections.data(),multipliers.data(),shifts.data(),zy)) : qnc_load(device,weights.data(),m,k);
                    if(!rc)resident=this;
                }
                if(!rc)rc=quantized ? qnc_run_bulk(device,x,t,static_cast<uint8_t*>(physical_ptr)) : qnc_run_i8(device,packed.data(),t,acc.data());
                if(rc) {resident=nullptr;throw std::runtime_error("FPGA transport/protocol failed: "+std::to_string(rc));}
                ++physical_calls;
            }
        }
        if(quantized && !emulate)return;
        int64_t dims[3]={1,m,t};OrtValue* out=nullptr;
        check(api->KernelContext_GetOutput(c,0,dims,3,&out));void* ptr=nullptr;
        check(api->GetTensorMutableData(out,&ptr));auto* y=static_cast<uint8_t*>(ptr);
        if(quantized) {
            for(int64_t o=0;o<m;o++)for(int64_t p=0;p<t;p++) {
                const int64_t total=int64_t(acc[o*t+p])+corrections[o];
                if(total<INT32_MIN || total>INT32_MAX)throw std::runtime_error("Affine sum overflow");
                const int64_t product=total*multipliers[o];const unsigned shift=shifts[o];
                // Floor division explicitly; C++ truncation differs for negatives.
                int64_t denominator=int64_t(1)<<shift;
                int64_t quotient=product/denominator,remainder=product%denominator;
                if(remainder<0) {quotient--;remainder+=denominator;}
                if(remainder>denominator/2 || (remainder==denominator/2 && (quotient&1)))quotient++;
                y[o*t+p]=uint8_t(std::clamp<int64_t>(quotient+zy,0,255));
            }
            return;
        }
        for(int64_t o=0;o<m;++o) {
            const int64_t correction=int64_t(128-int(zx))*sums[o]+bias[o];
            const float multiplier=(sx*sw[o])/sy;
            int64_t p=0;
#if defined(__aarch64__)
            // Check actual accumulator extrema before vector addition. Bias
            // channels near INT32 bounds cannot silently wrap in NEON.
            int32x4_t low=vdupq_n_s32(INT32_MAX),high=vdupq_n_s32(INT32_MIN);
            for(int64_t j=0;j+4<=t;j+=4) {
                int32x4_t v=vld1q_s32(acc.data()+o*t+j);
                low=vminq_s32(low,v);high=vmaxq_s32(high,v);
            }
            if(correction>=INT32_MIN && correction<=INT32_MAX &&
               int64_t(vminvq_s32(low))+correction>=INT32_MIN &&
               int64_t(vmaxvq_s32(high))+correction<=INT32_MAX) {
                for(;p+4<=t;p+=4) {
                    int32x4_t v=vaddq_s32(vld1q_s32(acc.data()+o*t+p),vdupq_n_s32(int32_t(correction)));
                    float32x4_t rounded=vrndnq_f32(vmulq_f32(vcvtq_f32_s32(v),vdupq_n_f32(multiplier)));
                    float32x4_t biased=vaddq_f32(rounded,vdupq_n_f32(float(zy)));
                    biased=vmaxq_f32(vdupq_n_f32(0),vminq_f32(vdupq_n_f32(255),biased));
                    uint16x4_t narrow=vmovn_u32(vcvtq_u32_f32(biased));
                    uint8x8_t bytes=vmovn_u16(vcombine_u16(narrow,vdup_n_u16(0)));
                    uint32_t word=vget_lane_u32(vreinterpret_u32_u8(bytes),0);
                    memcpy(y+o*t+p,&word,4);
                }
            }
#endif
            for(;p<t;++p) {
                const int64_t total=int64_t(acc[o*t+p])+correction;
                if(total<std::numeric_limits<int32_t>::min() || total>std::numeric_limits<int32_t>::max())
                    throw std::runtime_error("Pointwise accumulator overflow");
                // Explicit nearest-even with no dependence on ambient rounding.
                const float scaled=float(total)*multiplier;
                const float floor=std::floor(scaled),fraction=scaled-floor;
                float rounded=floor+((fraction>0.5f || (fraction==0.5f && std::fmod(floor,2.f)!=0.f))?1.f:0.f);
                y[o*t+p]=uint8_t(std::max(0.f,std::min(255.f,rounded+zy)));
            }
        }
    }
};
OrtCustomOp physical={}, oracle={},quant_physical={},quant_oracle={},repack_physical={};
OrtStatus* ORT_API_CALL create(const OrtCustomOp* op,const OrtApi* a,const OrtKernelInfo* info,void** out) {
    api=a;try {*out=new Kernel(info,op==&oracle || op==&quant_oracle,op==&quant_physical || op==&quant_oracle || op==&repack_physical,op==&quant_physical);return nullptr;}
    catch(const std::exception& e){return a->CreateStatus(ORT_FAIL,e.what());}
}
OrtStatus* ORT_API_CALL compute(void* p,OrtKernelContext* c) {
    try {static_cast<Kernel*>(p)->compute(c);return nullptr;}
    catch(const std::exception& e){return api->CreateStatus(ORT_FAIL,e.what());}
}
void ORT_API_CALL destroy(void* p) {
    std::lock_guard<std::mutex> lock(device_mutex);if(resident==p)resident=nullptr;delete static_cast<Kernel*>(p);
}
const char* ORT_API_CALL name(const OrtCustomOp* p){return p==&repack_physical?"FpgaBulkPointwise":p==&oracle?"OraclePointwise":p==&quant_oracle?"OracleBulkPointwise":p==&quant_physical?"FpgaPrepackedPointwise":"FpgaPointwise";}
const char* ORT_API_CALL provider(const OrtCustomOp*){return "CPUExecutionProvider";}
size_t ORT_API_CALL inputs(const OrtCustomOp*){return 9;}
size_t ORT_API_CALL outputs(const OrtCustomOp*){return 1;}
ONNXTensorElementDataType ORT_API_CALL input_type(const OrtCustomOp*,size_t i) {
    if(i==1 || i==4 || i==6)return ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT;
    if(i==3 || i==5)return ONNX_TENSOR_ELEMENT_DATA_TYPE_INT8;
    if(i==8)return ONNX_TENSOR_ELEMENT_DATA_TYPE_INT32;
    return ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8;
}
ONNXTensorElementDataType ORT_API_CALL output_type(const OrtCustomOp*,size_t){return ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8;}
OrtCustomOpInputOutputCharacteristic ORT_API_CALL characteristic(const OrtCustomOp*,size_t){return INPUT_OUTPUT_REQUIRED;}
OrtMemType ORT_API_CALL memory(const OrtCustomOp*,size_t){return OrtMemTypeDefault;}
std::vector<OrtCustomOpDomain*> domains;
}
extern "C" ORT_EXPORT OrtStatus* ORT_API_CALL RegisterCustomOps(OrtSessionOptions* options,const OrtApiBase* base) {
    api=base->GetApi(ORT_API_VERSION);if(!api)return nullptr;
    for(auto* op:{&physical,&oracle,&quant_physical,&quant_oracle,&repack_physical}) {
        *op={};op->version=ORT_API_VERSION;op->GetName=name;op->GetExecutionProviderType=provider;
        op->GetInputTypeCount=inputs;op->GetOutputTypeCount=outputs;op->GetInputType=input_type;
        op->GetOutputType=output_type;op->GetInputCharacteristic=characteristic;
        op->GetOutputCharacteristic=characteristic;op->GetInputMemoryType=memory;
        op->CreateKernelV2=create;op->KernelComputeV2=compute;op->KernelDestroy=destroy;
    }
    OrtCustomOpDomain* domain=nullptr;OrtStatus* status=api->CreateCustomOpDomain("prototype.fpga",&domain);
    if(status)return status;
    status=api->CustomOpDomain_Add(domain,&physical);if(!status)status=api->CustomOpDomain_Add(domain,&oracle);
    if(!status)status=api->CustomOpDomain_Add(domain,&quant_physical);
    if(!status)status=api->CustomOpDomain_Add(domain,&quant_oracle);
    if(!status)status=api->CustomOpDomain_Add(domain,&repack_physical);
    if(!status)status=api->AddCustomOpDomain(options,domain);
    if(status){api->ReleaseCustomOpDomain(domain);return status;}
    domains.push_back(domain);return nullptr;
}
extern "C" void fpga_ort_stats(qnc_stats* out,uint64_t* calls,uint64_t* emulated) {
    std::lock_guard<std::mutex> lock(device_mutex);*out={};if(device)qnc_get_stats(device,out);
    *calls=physical_calls;*emulated=oracle_calls;
}
extern "C" void fpga_ort_profile(qnc_profile* out) {
    std::lock_guard<std::mutex> lock(device_mutex);*out={};if(device)qnc_get_profile(device,out);
}
