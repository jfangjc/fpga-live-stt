"""Create an isolated software oracle for a shared-input residual branch.

The physical branch deliberately rejects execution until a matching protocol
and hardware have passed their own gates. Existing measured sources are retained.
"""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'software/ort_fpga_stream_registered';dest=ROOT/'software/ort_fpga_stream_branch'
assert not dest.exists(),'Refusing to overwrite branch work'
dest.mkdir()
for p in source.iterdir():
    if p.is_file() and (p.suffix in ('.c','.cc','.h','.py','.sh') or p.name=='Makefile'):
        shutil.copy2(p,dest/p.name)
shutil.copytree(source/'include',dest/'include')
text=(dest/'pointwise.cc').read_text()
def replace(old,new):
    global text
    assert old in text,old
    text=text.replace(old,new)
replace('bool emulate;std::vector<Stage>', 'bool emulate,branch;int64_t residual_stride=1;std::vector<Stage>')
replace('Chain(const OrtKernelInfo* info,bool oracle):emulate(oracle){','Chain(const OrtKernelInfo* info,bool oracle,bool residual_branch=false):emulate(oracle),branch(residual_branch){')
index=text.index('  int constant=0;const OrtValue* value=nullptr;',text.index('struct Chain {'))
text=text[:index]+'  if(branch){check(api->KernelInfoGetAttribute_int64(info,"residual_stride",&residual_stride));require(residual_stride==1||residual_stride==2,"Unsupported residual stride");}\n'+text[index:]
replace('require(count>0&&count<=8,"Invalid chain length");','require(count>0&&count<=8&&(!branch||count>=2),"Invalid chain length");')
replace('put(4,17|(256u<<16))','put(4,(branch?18:17)|(256u<<16))')
replace('auto x=data<uint8_t>(xv);std::lock_guard<std::mutex> lock(mutex);','uint8_t* residual=nullptr;\n  if(branch){auto rdims=dims;rdims[2]=(dims[2]+residual_stride-1)/residual_stride;OrtValue* value=nullptr;check(api->KernelContext_GetOutput(context,1,rdims.data(),3,&value));void* pointer=nullptr;check(api->GetTensorMutableData(value,&pointer));residual=static_cast<uint8_t*>(pointer);}\n  auto x=data<uint8_t>(xv);std::lock_guard<std::mutex> lock(mutex);')
replace('b[o*t+p]=stage+1==stages.size()?q:', 'b[o*t+p]=(branch&&stage==0)||stage+1==stages.size()?q:')
replace('    require(b>=INT32_MIN&&b<=INT32_MAX,"Chain correction overflow");s.corrections[o]=int32_t(b);', '    if(branch && &s==stages.data()){uint32_t bits=uint32_t(uint64_t(b));std::memcpy(&s.corrections[o],&bits,sizeof(bits));}\n    else {require(b>=INT32_MIN&&b<=INT32_MAX,"Chain correction overflow");s.corrections[o]=int32_t(b);}')
replace('     uint8_t q=s.pw.round(sum,o);','     if(branch&&stage==0){uint32_t bits=uint32_t(uint64_t(sum));int32_t wrapped;std::memcpy(&wrapped,&bits,sizeof(bits));sum=wrapped;}\n     uint8_t q=s.pw.round(sum,o);')
replace('    a.swap(b);','    if(branch&&stage==0){size_t rt=(t+residual_stride-1)/residual_stride;for(size_t c=0;c<256;c++)for(size_t p=0;p<rt;p++)residual[c*rt+p]=b[c*t+p*residual_stride];}else a.swap(b);')
index=text.index('struct Chain {')
head,body=text[:index],text[index:]
assert '   if(!device){\n    std::ifstream version' in body
body=body.replace('   if(!device){\n    std::ifstream version', '   require(!branch,"Physical residual branch protocol is not yet implemented or qualified");\n   if(!device){\n    std::ifstream version',1)
text=head+body
replace('OrtCustomOp physical={},oracle={};','OrtCustomOp physical={},oracle={},physical_branch={},oracle_branch={};')
replace('new Chain(info,op==&oracle)','new Chain(info,op==&oracle||op==&oracle_branch,op==&physical_branch||op==&oracle_branch)')
replace('return p==&oracle?"OracleChain":"FpgaChain";', 'return p==&oracle_branch?"OracleBranch":p==&physical_branch?"FpgaBranch":p==&oracle?"OracleChain":"FpgaChain";')
replace('size_t ORT_API_CALL outputs(const OrtCustomOp*){return 1;}', 'size_t ORT_API_CALL outputs(const OrtCustomOp* p){return p==&physical_branch||p==&oracle_branch?2:1;}')
replace('for(auto op:{&physical,&oracle})','for(auto op:{&physical,&oracle,&physical_branch,&oracle_branch})')
replace('"prototype.fpga.stream.registered"','"prototype.fpga.stream.branch"')
replace('s=api->CustomOpDomain_Add(domain,&physical);if(!s)s=api->CustomOpDomain_Add(domain,&oracle);','for(auto op:{&physical,&oracle,&physical_branch,&oracle_branch}){if(!s)s=api->CustomOpDomain_Add(domain,op);}')
(dest/'pointwise.cc').write_text(text)
print('Created software branch oracle; physical branch explicitly unavailable')
