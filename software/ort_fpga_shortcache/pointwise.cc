// Native retained depthwise/mask/pointwise custom operator. Experimental ABI.
// Physical path performs no host depthwise convolution and never falls back.
#include "include/onnxruntime_c_api.h"
extern "C" {
#include "qnc.h"
}
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>
namespace {
const OrtApi* api;
std::mutex mutex;
qnc* device=nullptr;
const void* residents[32]={};
uint64_t physical_calls=0,oracle_calls=0;
void check(OrtStatus* s){if(s){std::string e=api->GetErrorMessage(s);api->ReleaseStatus(s);throw std::runtime_error(e);}}
void require(bool yes,const char* e){if(!yes)throw std::runtime_error(e);}
std::vector<int64_t> shape(const OrtValue* v){
 OrtTensorTypeAndShapeInfo* info=nullptr;check(api->GetTensorTypeAndShape(v,&info));
 size_t n=0;OrtStatus* s=api->GetDimensionsCount(info,&n);
 if(s){api->ReleaseTensorTypeAndShapeInfo(info);check(s);}
 std::vector<int64_t> d(n);s=api->GetDimensions(info,d.data(),n);api->ReleaseTensorTypeAndShapeInfo(info);check(s);return d;
}
template<class T>const T* data(const OrtValue* v){const void* p=nullptr;check(api->GetTensorData(v,&p));return static_cast<const T*>(p);}
size_t elements(const OrtValue* v){size_t n=1;for(auto d:shape(v)){require(d>=0,"Invalid constant dimension");n*=d;}return n;}
const OrtValue* input(OrtKernelContext* c,size_t i){const OrtValue* v=nullptr;check(api->KernelContext_GetInput(c,i,&v));require(v,"Missing fused input");return v;}
struct Quant {
 std::vector<int8_t> w;
 std::vector<int32_t> bias,mult;
 std::vector<uint8_t> shifts;
 uint8_t zx=0,zy=0;
 int64_t m=0,k=0,width=0;
 void init(const OrtValue* xscale,const OrtValue* xzero,const OrtValue* weight,const OrtValue* wscale,
           const OrtValue* wzero,const OrtValue* yscale,const OrtValue* yzero,const OrtValue* b,bool dw){
  auto dims=shape(weight);require(dims.size()==3,"Invalid weight rank");
  m=dims[0];k=dims[1];width=dims[2];
  require(m>0 && m<=1024 && k>0 && k<=1024 && (dw?(k==1 && width>=11 && width<=21 && (width&1)):width==1),"Unsupported fused weight shape");
  require(elements(xscale)==1 && elements(xzero)==1 && elements(yscale)==1 && elements(yzero)==1,"Quantization must be scalar");
  require(elements(wscale)==size_t(m) && (elements(wzero)==1 || elements(wzero)==size_t(m)),"Invalid weight quantization shape");
  require(shape(b)==std::vector<int64_t>{m},"Invalid bias shape");
  const float sx=*data<float>(xscale),sy=*data<float>(yscale);zx=*data<uint8_t>(xzero);zy=*data<uint8_t>(yzero);
  require(std::isfinite(sx)&&sx>0&&std::isfinite(sy)&&sy>0,"Invalid scale");
  const float* sw=data<float>(wscale);const int8_t* zw=data<int8_t>(wzero);
  w.assign(data<int8_t>(weight),data<int8_t>(weight)+m*k*width);
  bias.assign(data<int32_t>(b),data<int32_t>(b)+m);mult.resize(m);shifts.resize(m);
  for(int64_t o=0;o<m;o++){
   require(zw[elements(wzero)==1?0:o]==0 && std::isfinite(sw[o]) && sw[o]>0,"Symmetric weight quantization required");
   float ratio=(sx*sw[o])/sy;require(std::isfinite(ratio)&&ratio>0,"Invalid affine ratio");
   if(ratio<=std::ldexp(1.f,-32)){mult[o]=0;shifts[o]=1;}
   else {
    int exponent;double significand=std::frexp(double(ratio),&exponent);
    int64_t multiplier=int64_t(std::nearbyint(std::ldexp(significand,31)));
    if(multiplier==(int64_t(1)<<31)){multiplier>>=1;exponent++;}
    int shift=31-exponent;require(shift>=1&&shift<=62,"Unsupported affine shift");
    mult[o]=int32_t(multiplier);shifts[o]=uint8_t(shift);
   }
  }
 }
 uint8_t round(int64_t sum,int64_t o)const{
  require(sum>=INT32_MIN&&sum<=INT32_MAX,"Fused accumulator overflow");
  int64_t product=sum*mult[o],den=int64_t(1)<<shifts[o];
  int64_t q=product/den,r=product%den;if(r<0){q--;r+=den;}
  if(r>den/2 || (r==den/2 && (q&1)))q++;
  return uint8_t(std::clamp<int64_t>(q+zy,0,255));
 }
};
struct Kernel {
 bool emulate,initialized=false;Quant dw,pw;std::vector<int32_t> corrections;
 explicit Kernel(const OrtKernelInfo* info,bool oracle):emulate(oracle){
  for(size_t i=1;i<15;i++){int constant=0;const OrtValue* v=nullptr;
   check(api->KernelInfoGetConstantInput_tensor(info,i,&constant,&v));require(constant,"Fused quantization, weights and bias must be constant");}
 }
 void compute(OrtKernelContext* c){
  const OrtValue* v[16];for(size_t i=0;i<16;i++)v[i]=input(c,i);
  auto xs=shape(v[0]);require(xs.size()==3 && xs[0]==1 && xs[2]>0 && xs[2]<=(emulate?4096:256),"Unsupported fused input shape");
  auto ms=shape(v[15]);require(ms==std::vector<int64_t>({1,1,xs[2]}),"Expected broadcast invalid-time mask");
  if(!initialized){
   dw.init(v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],true);
   pw.init(v[6],v[7],v[9],v[10],v[11],v[12],v[13],v[14],false);
   require(pw.k==dw.m,"Depthwise/pointwise channel mismatch");
   corrections.resize(pw.m);
   for(int64_t o=0;o<pw.m;o++){
    int64_t sum=0;for(int64_t i=0;i<pw.k;i++)sum+=pw.w[o*pw.k+i];
    int64_t b=int64_t(pw.bias[o])+int64_t(128-int(pw.zx))*sum;
    require(b>=INT32_MIN&&b<=INT32_MAX,"Pointwise bias correction overflow");corrections[o]=int32_t(b);
   }
   initialized=true;
  }
  require(xs[1]==dw.m && dw.m==256 && pw.m==256 && pw.k==256,"Cache requires fixed 256-channel pairs");
  const bool* mask=data<bool>(v[15]);size_t t=size_t(xs[2]),valid_t=t;
  for(size_t p=0;p<t;p++)if(mask[p]){valid_t=p;break;}
  for(size_t p=valid_t;p<t;p++)require(mask[p],"Invalid-time mask must be a suffix");
  int64_t dims[3]={1,pw.m,int64_t(t)};OrtValue* out=nullptr;check(api->KernelContext_GetOutput(c,0,dims,3,&out));
  void* outptr=nullptr;check(api->GetTensorMutableData(out,&outptr));auto y=static_cast<uint8_t*>(outptr);
  const uint8_t* x=data<uint8_t>(v[0]);
  std::lock_guard<std::mutex> lock(mutex);
  if(emulate){
   std::vector<uint8_t> intermediate(dw.m*t);
   for(int64_t channel=0;channel<dw.m;channel++)for(size_t p=0;p<t;p++){
    int64_t sum=dw.bias[channel];
    for(int tap=0;tap<dw.width;tap++){int64_t idx=int64_t(p)+tap-dw.width/2;
     if(idx>=0&&idx<int64_t(t))sum+=int64_t(int(x[channel*t+idx])-int(dw.zx))*dw.w[channel*dw.width+tap];}
    uint8_t q=dw.round(sum,channel);intermediate[channel*t+p]=p<valid_t?q:dw.zy;
   }
   for(int64_t o=0;o<pw.m;o++)for(size_t p=0;p<t;p++){
    int64_t sum=pw.bias[o];for(int64_t i=0;i<pw.k;i++)sum+=int64_t(int(intermediate[i*t+p])-int(pw.zx))*pw.w[o*pw.k+i];
    y[o*t+p]=pw.round(sum,o);
   }
   oracle_calls++;
  }else{
   if(!device){
    std::ifstream version("/sys/module/qn_tile/parameters/short_cache_protocol");unsigned protocol=0;
    require(bool(version>>protocol)&&protocol==1,"Matching retained-pair driver required");
    device=qnc_open("/dev/qn-tile");require(device,"Cannot open physical FPGA");
   }
   unsigned slot=32;
   for(unsigned i=0;i<32;i++)if(residents[i]==this){slot=i;break;}
   bool needs_load=slot==32;
   if(needs_load){for(unsigned i=0;i<32;i++)if(!residents[i]){slot=i;break;}}
   require(slot<32,"At most thirty-two resident physical kernels per library are supported");
   int rc=qnc_select_slot(device,slot);
   if(!rc && needs_load){
    rc=qnc_load_quant(device,pw.w.data(),unsigned(pw.m),unsigned(pw.k),corrections.data(),pw.mult.data(),pw.shifts.data(),pw.zy);
    if(!rc)rc=qnc_load_depthwise(device,dw.w.data(),dw.bias.data(),dw.mult.data(),dw.shifts.data(),dw.zx,dw.zy,unsigned(dw.width));
    if(!rc)residents[slot]=this;
   }
   if(!rc)rc=qnc_run_pair(device,x,t,valid_t,y);
   if(rc){for(auto& owner:residents)owner=nullptr;throw std::runtime_error("Cached FPGA transport failed: "+std::to_string(rc));}
   physical_calls++;
  }
 }
};
OrtCustomOp physical={},oracle={};
OrtStatus* ORT_API_CALL create(const OrtCustomOp* op,const OrtApi* a,const OrtKernelInfo* info,void** out){
 api=a;try{*out=new Kernel(info,op==&oracle);return nullptr;}catch(const std::exception& e){return a->CreateStatus(ORT_FAIL,e.what());}}
OrtStatus* ORT_API_CALL compute(void* p,OrtKernelContext* c){try{static_cast<Kernel*>(p)->compute(c);return nullptr;}catch(const std::exception& e){return api->CreateStatus(ORT_FAIL,e.what());}}
void ORT_API_CALL destroy(void* p){std::lock_guard<std::mutex> lock(mutex);for(auto& owner:residents)if(owner==p)owner=nullptr;delete static_cast<Kernel*>(p);}
const char* ORT_API_CALL name(const OrtCustomOp* p){return p==&oracle?"OracleDepthwisePointwise":"FpgaDepthwisePointwise";}
const char* ORT_API_CALL provider(const OrtCustomOp*){return "CPUExecutionProvider";}
size_t ORT_API_CALL inputs(const OrtCustomOp*){return 16;}
size_t ORT_API_CALL outputs(const OrtCustomOp*){return 1;}
ONNXTensorElementDataType ORT_API_CALL input_type(const OrtCustomOp*,size_t i){
 if(i==1||i==4||i==6||i==10||i==12)return ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT;
 if(i==3||i==5||i==9||i==11)return ONNX_TENSOR_ELEMENT_DATA_TYPE_INT8;
 if(i==8||i==14)return ONNX_TENSOR_ELEMENT_DATA_TYPE_INT32;
 if(i==15)return ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL;
 return ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8;}
ONNXTensorElementDataType ORT_API_CALL output_type(const OrtCustomOp*,size_t){return ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8;}
OrtCustomOpInputOutputCharacteristic ORT_API_CALL characteristic(const OrtCustomOp*,size_t){return INPUT_OUTPUT_REQUIRED;}
OrtMemType ORT_API_CALL memory(const OrtCustomOp*,size_t){return OrtMemTypeDefault;}
std::vector<OrtCustomOpDomain*> domains;
}
extern "C" ORT_EXPORT OrtStatus* ORT_API_CALL RegisterCustomOps(OrtSessionOptions* options,const OrtApiBase* base){
 api=base->GetApi(ORT_API_VERSION);if(!api)return nullptr;
 for(auto op:{&physical,&oracle}){
  *op={};op->version=ORT_API_VERSION;op->GetName=name;op->GetExecutionProviderType=provider;
  op->GetInputTypeCount=inputs;op->GetOutputTypeCount=outputs;op->GetInputType=input_type;op->GetOutputType=output_type;
  op->GetInputCharacteristic=characteristic;op->GetOutputCharacteristic=characteristic;op->GetInputMemoryType=memory;
  op->CreateKernelV2=create;op->KernelComputeV2=compute;op->KernelDestroy=destroy;
 }
 OrtCustomOpDomain* domain=nullptr;OrtStatus* s=api->CreateCustomOpDomain("prototype.fpga.shortcache",&domain);if(s)return s;
 s=api->CustomOpDomain_Add(domain,&physical);if(!s)s=api->CustomOpDomain_Add(domain,&oracle);
 if(!s)s=api->AddCustomOpDomain(options,domain);
 if(s){api->ReleaseCustomOpDomain(domain);return s;}domains.push_back(domain);return nullptr;
}
extern "C" void fpga_ort_stats(qnc_stats* out,uint64_t* calls,uint64_t* emulated){std::lock_guard<std::mutex> lock(mutex);*out={};if(device)qnc_get_stats(device,out);*calls=physical_calls;*emulated=oracle_calls;}
extern "C" void fpga_ort_profile(qnc_profile* out){std::lock_guard<std::mutex> lock(mutex);*out={};if(device)qnc_get_profile(device,out);}
