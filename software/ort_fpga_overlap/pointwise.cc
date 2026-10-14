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
#include <chrono>
#include <condition_variable>
#include <exception>
#include <thread>
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

struct Stage {Quant dw,pw;std::vector<int32_t> corrections;uint8_t lookup[256],masked=0;};
template<class T>T read_value(const uint8_t*& p,const uint8_t* end){
 require(size_t(end-p)>=sizeof(T),"Truncated chain program");T v;std::memcpy(&v,p,sizeof(v));p+=sizeof(v);return v;
}
void raw_quant(Quant& q,float sx,float sy,const std::vector<float>& sw){
 require(std::isfinite(sx)&&sx>0&&std::isfinite(sy)&&sy>0,"Invalid chain scale");
 q.mult.resize(256);q.shifts.resize(256);
 for(int o=0;o<256;o++){
  require(std::isfinite(sw[o])&&sw[o]>0,"Invalid per-channel scale");
  float ratio=(sx*sw[o])/sy;require(std::isfinite(ratio)&&ratio>0,"Invalid chain affine ratio");
  if(ratio<=std::ldexp(1.f,-32)){q.mult[o]=0;q.shifts[o]=1;}
  else {int exponent;double significand=std::frexp(double(ratio),&exponent);
   int64_t multiplier=int64_t(std::nearbyint(std::ldexp(significand,31)));
   if(multiplier==(int64_t(1)<<31)){multiplier>>=1;exponent++;}
   int shift=31-exponent;require(shift>=1&&shift<=62,"Unsupported chain affine shift");
   q.mult[o]=int32_t(multiplier);q.shifts[o]=uint8_t(shift);
  }
 }
}
struct Chain {
 bool emulate;std::vector<Stage> stages;
 size_t xi,mi,yi;
 Chain(const OrtKernelInfo* info,bool oracle,size_t program=2,size_t x=0,size_t mask=1,size_t y=0):emulate(oracle),xi(x),mi(mask),yi(y){
  int constant=0;const OrtValue* value=nullptr;
  check(api->KernelInfoGetConstantInput_tensor(info,program,&constant,&value));require(constant,"Chain program must be constant");
  const uint8_t* p=data<uint8_t>(value);const uint8_t* end=p+elements(value);
  require(read_value<uint32_t>(p,end)==0x314e4843,"Invalid chain program magic");
  unsigned count=read_value<uint32_t>(p,end);require(count>0&&count<=32,"Invalid chain length");stages.resize(count);
  for(auto& s:stages){
   unsigned kernel=read_value<uint32_t>(p,end);require(kernel>=11&&kernel<=21&&(kernel&1),"Invalid chain kernel");
   s.dw.m=256;s.dw.k=1;s.dw.width=kernel;s.pw.m=256;s.pw.k=256;s.pw.width=1;
   auto zero=[&](){unsigned z=read_value<uint32_t>(p,end);require(z<=255,"Invalid chain zero point");return uint8_t(z);};
   s.dw.zx=zero();s.dw.zy=zero();s.pw.zx=s.dw.zy;s.pw.zy=zero();
   float sx=read_value<float>(p,end),sd=read_value<float>(p,end),sy=read_value<float>(p,end);
   std::vector<float> dwscale(256),pwscale(256);
   for(auto& x:dwscale)x=read_value<float>(p,end);for(auto& x:pwscale)x=read_value<float>(p,end);
   s.dw.bias.resize(256);s.pw.bias.resize(256);
   for(auto& x:s.dw.bias)x=read_value<int32_t>(p,end);for(auto& x:s.pw.bias)x=read_value<int32_t>(p,end);
   s.dw.w.resize(256*kernel);s.pw.w.resize(65536);
   for(auto& x:s.dw.w)x=read_value<int8_t>(p,end);for(auto& x:s.pw.w)x=read_value<int8_t>(p,end);
   for(auto& x:s.lookup)x=read_value<uint8_t>(p,end);s.masked=zero();
   raw_quant(s.dw,sx,sd,dwscale);raw_quant(s.pw,sd,sy,pwscale);s.corrections.resize(256);
   for(int o=0;o<256;o++){
    int64_t sum=0;for(int i=0;i<256;i++)sum+=s.pw.w[o*256+i];
    int64_t b=int64_t(s.pw.bias[o])+int64_t(128-int(s.pw.zx))*sum;
    require(b>=INT32_MIN&&b<=INT32_MAX,"Chain correction overflow");s.corrections[o]=int32_t(b);
   }
  }
  require(p==end,"Trailing chain program bytes");
 }
 void compute(OrtKernelContext* context){
  const OrtValue* xv=input(context,xi);const OrtValue* mv=input(context,mi);auto dims=shape(xv);
  require(dims.size()==3&&dims[0]==1&&dims[1]==256&&dims[2]>0&&dims[2]<=(emulate?4096:256),"Invalid chain activation shape");
  size_t t=size_t(dims[2]),valid_t=t;require(shape(mv)==std::vector<int64_t>{1,1,int64_t(t)},"Invalid chain mask shape");
  auto mask=data<bool>(mv);for(size_t p=0;p<t;p++)if(mask[p]){valid_t=p;break;}
  for(size_t p=valid_t;p<t;p++)require(mask[p],"Chain mask must be a suffix");
  OrtValue* output=nullptr;check(api->KernelContext_GetOutput(context,yi,dims.data(),3,&output));
  void* outptr=nullptr;check(api->GetTensorMutableData(output,&outptr));auto y=static_cast<uint8_t*>(outptr);
  auto x=data<uint8_t>(xv);std::lock_guard<std::mutex> lock(mutex);
  if(emulate){
   std::vector<uint8_t> a(x,x+256*t),b(256*t),intermediate(256*t);
   for(size_t stage=0;stage<stages.size();stage++){
    auto& s=stages[stage];
    for(int c=0;c<256;c++)for(size_t p=0;p<t;p++){
     int64_t sum=s.dw.bias[c];for(int tap=0;tap<s.dw.width;tap++){
      int64_t index=int64_t(p)+tap-s.dw.width/2;
      if(index>=0&&index<int64_t(t))sum+=int64_t(int(a[c*t+index])-int(s.dw.zx))*s.dw.w[c*s.dw.width+tap];
     }
     intermediate[c*t+p]=p<valid_t?s.dw.round(sum,c):s.dw.zy;
    }
    for(int o=0;o<256;o++)for(size_t p=0;p<t;p++){
     int64_t sum=s.pw.bias[o];for(int c=0;c<256;c++)sum+=int64_t(int(intermediate[c*t+p])-int(s.pw.zx))*s.pw.w[o*256+c];
     uint8_t q=s.pw.round(sum,o);
     b[o*t+p]=stage+1==stages.size()?q:p>=valid_t?s.masked:s.lookup[q];
    }
    a.swap(b);
   }
   std::memcpy(y,a.data(),256*t);oracle_calls+=stages.size();
  }else{
   if(!device){
    std::ifstream version("/sys/module/qn_tile/parameters/short_chain_protocol");unsigned protocol=0;
    require(bool(version>>protocol)&&protocol==1,"Matching retained-chain driver required");
    device=qnc_open("/dev/qn-tile");require(device,"Cannot open chain FPGA");
   }
   std::vector<qnc_chain_stage> program;int rc=0;
   for(auto& s:stages){
    unsigned slot=32;for(unsigned i=0;i<32;i++)if(residents[i]==&s){slot=i;break;}
    bool load=slot==32;if(load)for(unsigned i=0;i<32;i++)if(!residents[i]){slot=i;break;}
    require(slot<32,"Resident chain slots exhausted");rc=qnc_select_slot(device,slot);
    if(!rc&&load){
     rc=qnc_load_quant(device,s.pw.w.data(),256,256,s.corrections.data(),s.pw.mult.data(),s.pw.shifts.data(),s.pw.zy);
     if(!rc)rc=qnc_load_depthwise(device,s.dw.w.data(),s.dw.bias.data(),s.dw.mult.data(),s.dw.shifts.data(),s.dw.zx,s.dw.zy,unsigned(s.dw.width));
     if(!rc)residents[slot]=&s;
    }
    if(rc)break;program.push_back({slot,s.masked,s.lookup});
   }
   if(!rc)rc=qnc_run_chain(device,program.data(),unsigned(program.size()),x,t,valid_t,y);
   if(rc){for(auto& owner:residents)owner=nullptr;throw std::runtime_error("Retained chain transport failed: "+std::to_string(rc));}
   physical_calls+=stages.size();
  }
 }
};

struct OverlapProfile {uint64_t calls=0;double residual_seconds=0,device_seconds=0,join_seconds=0,total_seconds=0;};
OverlapProfile overlap_profile;std::mutex profile_mutex;
using Clock=std::chrono::steady_clock;
double seconds(Clock::time_point a,Clock::time_point b){return std::chrono::duration<double>(b-a).count();}
struct Runner {virtual ~Runner()=default;virtual void compute(OrtKernelContext*)=0;virtual Chain& chain()=0;};
struct Normal:Runner {Chain engine;Normal(const OrtKernelInfo* info,bool oracle):engine(info,oracle){}
 void compute(OrtKernelContext* c)override{engine.compute(c);}Chain& chain()override{return engine;}};
struct Parallel:Runner {
 Chain engine;OrtOp* residual=nullptr;int64_t stride=0,channels=0;
 std::thread worker;std::mutex work_mutex;std::condition_variable work_cv;
 bool stopping=false,pending=false,finished=true;OrtKernelContext* job=nullptr;std::exception_ptr failure;
 double device_seconds=0;
 Parallel(const OrtKernelInfo* info,bool oracle):engine(info,oracle,11,9,10,1){
  check(api->KernelInfoGetAttribute_int64(info,"res_stride",&stride));require(stride==1||stride==2,"Invalid residual stride");
  int constant=0;const OrtValue* w=nullptr;check(api->KernelInfoGetConstantInput_tensor(info,3,&constant,&w));
  require(constant,"Residual weights must be constant");auto wd=shape(w);require(wd.size()==3&&wd[2]==1,"Invalid residual weights");channels=wd[0];
  std::vector<OrtOpAttr*> attributes;
  auto attribute=[&](const char* name,const int64_t* values,int count,OrtOpAttrType type){OrtOpAttr* attr=nullptr;
   check(api->CreateOpAttr(name,values,count,type,&attr));attributes.push_back(attr);};
  int64_t one=1,pads[2]={0,0};
  try{
   attribute("group",&one,1,ORT_OP_ATTR_INT);attribute("kernel_shape",&one,1,ORT_OP_ATTR_INTS);
   attribute("dilations",&one,1,ORT_OP_ATTR_INTS);attribute("pads",pads,2,ORT_OP_ATTR_INTS);attribute("strides",&stride,1,ORT_OP_ATTR_INTS);
   const char* names[]={"T1","T2","T3"};ONNXTensorElementDataType types[]={ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8,ONNX_TENSOR_ELEMENT_DATA_TYPE_INT8,ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8};
   check(api->CreateOp(info,"QLinearConv","",10,names,types,3,attributes.data(),int(attributes.size()),9,1,&residual));
  }catch(...){for(auto attr:attributes)api->ReleaseOpAttr(attr);throw;}
  for(auto attr:attributes)api->ReleaseOpAttr(attr);
  try{worker=std::thread([this](){work();});}catch(...){api->ReleaseOp(residual);throw;}
 }
 void work(){
  std::unique_lock<std::mutex> lock(work_mutex);
  while(true){work_cv.wait(lock,[this](){return pending||stopping;});if(stopping)return;
   auto context=job;pending=false;lock.unlock();auto start=Clock::now();std::exception_ptr error;
   try{engine.compute(context);}catch(...){error=std::current_exception();}
   double duration=seconds(start,Clock::now());lock.lock();failure=error;device_seconds=duration;finished=true;work_cv.notify_all();
  }
 }
 ~Parallel(){
  {std::lock_guard<std::mutex> lock(work_mutex);stopping=true;work_cv.notify_all();}
  worker.join();api->ReleaseOp(residual);
 }
 Chain& chain()override{return engine;}
 void compute(OrtKernelContext* context)override{
  const OrtValue* values[9];for(size_t i=0;i<9;i++)values[i]=input(context,i);
  auto dims=shape(values[0]);require(dims.size()==3&&dims[0]==1&&dims[2]>0,"Invalid residual input");
  dims[1]=channels;dims[2]=(dims[2]+stride-1)/stride;OrtValue* output=nullptr;
  check(api->KernelContext_GetOutput(context,0,dims.data(),3,&output));
  // Allocate both outputs before the worker starts using this context.
  auto chain_dims=shape(input(context,9));OrtValue* chain_output=nullptr;
  check(api->KernelContext_GetOutput(context,1,chain_dims.data(),3,&chain_output));
  auto start=Clock::now();
  {std::lock_guard<std::mutex> lock(work_mutex);require(finished,"Overlapping calls on one kernel are unsupported");
   finished=false;failure=nullptr;job=context;pending=true;work_cv.notify_all();}
  std::exception_ptr cpu_failure;auto cpu_start=Clock::now();
  try{check(api->InvokeOp(context,residual,values,9,&output,1));}catch(...){cpu_failure=std::current_exception();}
  auto cpu_end=Clock::now();std::exception_ptr device_failure;double duration;
  {std::unique_lock<std::mutex> lock(work_mutex);work_cv.wait(lock,[this](){return finished;});device_failure=failure;duration=device_seconds;}
  auto end=Clock::now();
  {std::lock_guard<std::mutex> lock(profile_mutex);overlap_profile.calls++;
   overlap_profile.residual_seconds+=seconds(cpu_start,cpu_end);overlap_profile.device_seconds+=duration;
   overlap_profile.join_seconds+=seconds(cpu_end,end);overlap_profile.total_seconds+=seconds(start,end);}
  if(cpu_failure)std::rethrow_exception(cpu_failure);if(device_failure)std::rethrow_exception(device_failure);
 }
};
OrtCustomOp physical={},oracle={},physical_overlap={},oracle_overlap={};
bool parallel(const OrtCustomOp* op){return op==&physical_overlap||op==&oracle_overlap;}
bool emulated(const OrtCustomOp* op){return op==&oracle||op==&oracle_overlap;}
OrtStatus* ORT_API_CALL create(const OrtCustomOp* op,const OrtApi* a,const OrtKernelInfo* info,void** out){
 api=a;try{*out=parallel(op)?static_cast<Runner*>(new Parallel(info,emulated(op))):static_cast<Runner*>(new Normal(info,emulated(op)));return nullptr;}
 catch(const std::exception& e){return a->CreateStatus(ORT_FAIL,e.what());}}
OrtStatus* ORT_API_CALL compute(void* p,OrtKernelContext* c){try{static_cast<Runner*>(p)->compute(c);return nullptr;}
 catch(const std::exception& e){return api->CreateStatus(ORT_FAIL,e.what());}}
void ORT_API_CALL destroy(void* p){auto runner=static_cast<Runner*>(p);
 {std::lock_guard<std::mutex> lock(mutex);for(auto& s:runner->chain().stages)for(auto& owner:residents)if(owner==&s)owner=nullptr;}
 delete runner;}
const char* ORT_API_CALL name(const OrtCustomOp* p){return parallel(p)?(emulated(p)?"OracleResidualChain":"FpgaResidualChain"):(emulated(p)?"OracleChain":"FpgaChain");}
const char* ORT_API_CALL provider(const OrtCustomOp*){return "CPUExecutionProvider";}
size_t ORT_API_CALL inputs(const OrtCustomOp* p){return parallel(p)?12:3;}
size_t ORT_API_CALL outputs(const OrtCustomOp* p){return parallel(p)?2:1;}
ONNXTensorElementDataType ORT_API_CALL input_type(const OrtCustomOp* p,size_t i){
 if(!parallel(p))return i==1?ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL:ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8;
 if(i==1||i==4||i==6)return ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT;
 if(i==3||i==5)return ONNX_TENSOR_ELEMENT_DATA_TYPE_INT8;
 if(i==8)return ONNX_TENSOR_ELEMENT_DATA_TYPE_INT32;
 return i==10?ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL:ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8;
}
ONNXTensorElementDataType ORT_API_CALL output_type(const OrtCustomOp*,size_t){return ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8;}
OrtCustomOpInputOutputCharacteristic ORT_API_CALL characteristic(const OrtCustomOp*,size_t){return INPUT_OUTPUT_REQUIRED;}
OrtMemType ORT_API_CALL memory(const OrtCustomOp*,size_t){return OrtMemTypeDefault;}
std::vector<OrtCustomOpDomain*> domains;
}
extern "C" ORT_EXPORT OrtStatus* ORT_API_CALL RegisterCustomOps(OrtSessionOptions* options,const OrtApiBase* base){
 api=base->GetApi(ORT_API_VERSION);if(!api)return nullptr;
 for(auto op:{&physical,&oracle,&physical_overlap,&oracle_overlap}){
  *op={};op->version=ORT_API_VERSION;op->GetName=name;op->GetExecutionProviderType=provider;
  op->GetInputTypeCount=inputs;op->GetOutputTypeCount=outputs;op->GetInputType=input_type;op->GetOutputType=output_type;
  op->GetInputCharacteristic=characteristic;op->GetOutputCharacteristic=characteristic;op->GetInputMemoryType=memory;
  op->CreateKernelV2=create;op->KernelComputeV2=compute;op->KernelDestroy=destroy;
 }
 OrtCustomOpDomain* domain=nullptr;OrtStatus* s=api->CreateCustomOpDomain("prototype.fpga.overlap",&domain);if(s)return s;
 for(auto op:{&physical,&oracle,&physical_overlap,&oracle_overlap})if(!s)s=api->CustomOpDomain_Add(domain,op);
 if(!s)s=api->AddCustomOpDomain(options,domain);
 if(s){api->ReleaseCustomOpDomain(domain);return s;}domains.push_back(domain);return nullptr;
}
extern "C" void fpga_ort_stats(qnc_stats* out,uint64_t* calls,uint64_t* emulated){std::lock_guard<std::mutex> lock(mutex);*out={};if(device)qnc_get_stats(device,out);*calls=physical_calls;*emulated=oracle_calls;}
extern "C" void fpga_ort_profile(qnc_profile* out){std::lock_guard<std::mutex> lock(mutex);*out={};if(device)qnc_get_profile(device,out);}
extern "C" void fpga_overlap_stats(OverlapProfile* out){std::lock_guard<std::mutex> lock(profile_mutex);*out=overlap_profile;}
