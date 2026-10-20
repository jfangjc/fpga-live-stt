"""Generate an isolated chain-only operator from the verified Quant arithmetic."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'software/ort_fpga_shortwide/pointwise.cc').read_text()
prefix=source[:source.index('OrtCustomOp physical={},oracle={};')]
body=r'''
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
 Chain(const OrtKernelInfo* info,bool oracle):emulate(oracle){
  int constant=0;const OrtValue* value=nullptr;
  check(api->KernelInfoGetConstantInput_tensor(info,2,&constant,&value));require(constant,"Chain program must be constant");
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
  const OrtValue* xv=input(context,0);const OrtValue* mv=input(context,1);auto dims=shape(xv);
  require(dims.size()==3&&dims[0]==1&&dims[1]==256&&dims[2]>0&&dims[2]<=(emulate?4096:256),"Invalid chain activation shape");
  size_t t=size_t(dims[2]),valid_t=t;require(shape(mv)==std::vector<int64_t>{1,1,int64_t(t)},"Invalid chain mask shape");
  auto mask=data<bool>(mv);for(size_t p=0;p<t;p++)if(mask[p]){valid_t=p;break;}
  for(size_t p=valid_t;p<t;p++)require(mask[p],"Chain mask must be a suffix");
  OrtValue* output=nullptr;check(api->KernelContext_GetOutput(context,0,dims.data(),3,&output));
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
OrtCustomOp physical={},oracle={};
OrtStatus* ORT_API_CALL create(const OrtCustomOp* op,const OrtApi* a,const OrtKernelInfo* info,void** out){
 api=a;try{*out=new Chain(info,op==&oracle);return nullptr;}catch(const std::exception& e){return a->CreateStatus(ORT_FAIL,e.what());}}
OrtStatus* ORT_API_CALL compute(void* p,OrtKernelContext* c){try{static_cast<Chain*>(p)->compute(c);return nullptr;}catch(const std::exception& e){return api->CreateStatus(ORT_FAIL,e.what());}}
void ORT_API_CALL destroy(void* p){std::lock_guard<std::mutex> lock(mutex);auto chain=static_cast<Chain*>(p);
 for(auto& s:chain->stages)for(auto& owner:residents)if(owner==&s)owner=nullptr;delete chain;}
const char* ORT_API_CALL name(const OrtCustomOp* p){return p==&oracle?"OracleChain":"FpgaChain";}
const char* ORT_API_CALL provider(const OrtCustomOp*){return "CPUExecutionProvider";}
size_t ORT_API_CALL inputs(const OrtCustomOp*){return 3;}
size_t ORT_API_CALL outputs(const OrtCustomOp*){return 1;}
ONNXTensorElementDataType ORT_API_CALL input_type(const OrtCustomOp*,size_t i){return i==1?ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL:ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8;}
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
 OrtCustomOpDomain* domain=nullptr;OrtStatus* s=api->CreateCustomOpDomain("prototype.fpga.chain",&domain);if(s)return s;
 s=api->CustomOpDomain_Add(domain,&physical);if(!s)s=api->CustomOpDomain_Add(domain,&oracle);
 if(!s)s=api->AddCustomOpDomain(options,domain);
 if(s){api->ReleaseCustomOpDomain(domain);return s;}domains.push_back(domain);return nullptr;
}
extern "C" void fpga_ort_stats(qnc_stats* out,uint64_t* calls,uint64_t* emulated){std::lock_guard<std::mutex> lock(mutex);*out={};if(device)qnc_get_stats(device,out);*calls=physical_calls;*emulated=oracle_calls;}
extern "C" void fpga_ort_profile(qnc_profile* out){std::lock_guard<std::mutex> lock(mutex);*out={};if(device)qnc_get_profile(device,out);}
'''
(ROOT/'software/ort_fpga_chain/pointwise.cc').write_text(prefix+body)
print('Generated chain custom operator with unchanged Q31 nearest-even arithmetic')
