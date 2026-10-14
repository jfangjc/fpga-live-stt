"""Build an isolated native residual/FPGA overlap variant from the chain core."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1];source=ROOT/'software/ort_fpga_chain';target=ROOT/'software/ort_fpga_overlap'
target.mkdir(parents=True,exist_ok=True)
for name in ('qnc.h','qnc_transport.c','build.sh'):shutil.copyfile(source/name,target/name)
shutil.copytree(source/'include',target/'include',dirs_exist_ok=True)
prefix=(source/'pointwise.cc').read_text().split('OrtCustomOp physical={},oracle={};')[0]
prefix=prefix.replace('#include <mutex>','#include <mutex>\n#include <chrono>\n#include <condition_variable>\n#include <exception>\n#include <thread>')
old='Chain(const OrtKernelInfo* info,bool oracle):emulate(oracle){'
new='size_t xi,mi,yi;\n Chain(const OrtKernelInfo* info,bool oracle,size_t program=2,size_t x=0,size_t mask=1,size_t y=0):emulate(oracle),xi(x),mi(mask),yi(y){'
assert prefix.count(old)==1;prefix=prefix.replace(old,new)
old='KernelInfoGetConstantInput_tensor(info,2,&constant,&value)';assert prefix.count(old)==1
prefix=prefix.replace(old,'KernelInfoGetConstantInput_tensor(info,program,&constant,&value)')
old='const OrtValue* xv=input(context,0);const OrtValue* mv=input(context,1);';assert prefix.count(old)==1
prefix=prefix.replace(old,'const OrtValue* xv=input(context,xi);const OrtValue* mv=input(context,mi);')
old='KernelContext_GetOutput(context,0,dims.data(),3,&output)';assert prefix.count(old)==1
prefix=prefix.replace(old,'KernelContext_GetOutput(context,yi,dims.data(),3,&output)')
body=r'''
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
'''
(target/'pointwise.cc').write_text(prefix+body)
print('Generated isolated overlap runtime; chain transport and arithmetic unchanged')
