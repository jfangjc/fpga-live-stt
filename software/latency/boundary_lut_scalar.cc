// Exact UINT8 lookup for DQ/activation/mask/Q boundaries. No FPGA accesses.
#include "../ort_fpga_shortwide/include/onnxruntime_c_api.h"
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>
namespace {
const OrtApi* api;
void check(OrtStatus* status) {
    if (status) { std::string text=api->GetErrorMessage(status); api->ReleaseStatus(status); throw std::runtime_error(text); }
}
std::vector<int64_t> shape(const OrtValue* value) {
    OrtTensorTypeAndShapeInfo* info=nullptr;
    check(api->GetTensorTypeAndShape(value,&info));
    size_t count=0;
    OrtStatus* status=api->GetDimensionsCount(info,&count);
    if(status) {api->ReleaseTensorTypeAndShapeInfo(info);check(status);}
    std::vector<int64_t> dims(count);
    status=api->GetDimensions(info,dims.data(),count);
    api->ReleaseTensorTypeAndShapeInfo(info);check(status);return dims;
}
template<class T> const T* data(const OrtValue* value) {
    const void* pointer=nullptr;check(api->GetTensorData(value,&pointer));return static_cast<const T*>(pointer);
}
struct Kernel {
    void compute(OrtKernelContext* context) {
        const OrtValue* values[3];
        for(size_t i=0;i<3;i++)check(api->KernelContext_GetInput(context,i,&values[i]));
        auto dims=shape(values[0]),maskdims=shape(values[1]),lutdims=shape(values[2]);
        if(dims.size()!=3 || dims[0]!=1 || dims[1]<=0 || dims[2]<=0 || lutdims!=std::vector<int64_t>{2,256})
            throw std::runtime_error("Invalid boundary tensor or LUT shape");
        if(maskdims!=std::vector<int64_t>{1,1,1} && maskdims!=std::vector<int64_t>{1,1,dims[2]})
            throw std::runtime_error("Invalid boundary mask broadcast");
        OrtValue* output=nullptr;check(api->KernelContext_GetOutput(context,0,dims.data(),dims.size(),&output));
        void* pointer=nullptr;check(api->GetTensorMutableData(output,&pointer));
        auto y=static_cast<uint8_t*>(pointer);auto x=data<uint8_t>(values[0]);
        auto lut=data<uint8_t>(values[2]);auto mask=data<bool>(values[1]);
        size_t times=static_cast<size_t>(dims[2]);
        if(maskdims[2]==1) {
            const uint8_t* table=lut+(mask[0]?256:0);
            for(size_t i=0;i<static_cast<size_t>(dims[1])*times;i++)y[i]=table[x[i]];
        } else {
            for(size_t c=0;c<static_cast<size_t>(dims[1]);c++)
                for(size_t t=0;t<times;t++)y[c*times+t]=lut[(mask[t]?256:0)+x[c*times+t]];
        }
    }
};
OrtCustomOp op={};
OrtStatus* ORT_API_CALL create(const OrtCustomOp*,const OrtApi* a,const OrtKernelInfo*,void** result) {
    api=a;try{*result=new Kernel();return nullptr;}catch(const std::exception& e){return api->CreateStatus(ORT_FAIL,e.what());}
}
OrtStatus* ORT_API_CALL compute(void* kernel,OrtKernelContext* context) {
    try{static_cast<Kernel*>(kernel)->compute(context);return nullptr;}catch(const std::exception& e){return api->CreateStatus(ORT_FAIL,e.what());}
}
void ORT_API_CALL destroy(void* kernel){delete static_cast<Kernel*>(kernel);}
const char* ORT_API_CALL name(const OrtCustomOp*){return "LookupMask";}
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
    op.version=ORT_API_VERSION;op.GetName=name;op.GetExecutionProviderType=provider;
    op.GetInputTypeCount=inputs;op.GetOutputTypeCount=outputs;op.GetInputType=input_type;op.GetOutputType=output_type;
    op.GetInputCharacteristic=characteristic;op.GetOutputCharacteristic=characteristic;op.GetInputMemoryType=memory;
    op.CreateKernelV2=create;op.KernelComputeV2=compute;op.KernelDestroy=destroy;
    OrtCustomOpDomain* domain=nullptr;OrtStatus* status=api->CreateCustomOpDomain("prototype.cpu.boundary",&domain);
    if(status)return status;
    status=api->CustomOpDomain_Add(domain,&op);if(!status)status=api->AddCustomOpDomain(options,domain);
    if(status){api->ReleaseCustomOpDomain(domain);return status;}
    domains.push_back(domain);return nullptr;
}
