"""Preserve InvokeOp experiment; use initialized CPU kernels for overlap."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1];source=ROOT/'software/ort_fpga_overlap';target=ROOT/'software/ort_fpga_overlap_session'
target.mkdir(parents=True,exist_ok=True)
for name in ('qnc.h','qnc_transport.c','build.sh'):shutil.copyfile(source/name,target/name)
shutil.copytree(source/'include',target/'include',dirs_exist_ok=True)
text=(source/'pointwise.cc').read_text().replace('OrtOp* residual=nullptr','OrtSession* residual=nullptr')
text=text.replace('struct Parallel:Runner {','OrtEnv* residual_env=nullptr;std::once_flag environment_once;\nstruct Parallel:Runner {')
begin=text.index('  std::vector<OrtOpAttr*> attributes;');end=text.index('  try{worker=std::thread',begin)
text=text[:begin]+r'''  int model_constant=0;const OrtValue* model=nullptr;
  check(api->KernelInfoGetConstantInput_tensor(info,12,&model_constant,&model));require(model_constant,"Residual CPU graph must be constant");
  OrtSessionOptions* options=nullptr;check(api->CreateSessionOptions(&options));
  try{
   check(api->SetIntraOpNumThreads(options,4));check(api->SetInterOpNumThreads(options,1));
   check(api->SetSessionExecutionMode(options,ORT_SEQUENTIAL));check(api->SetSessionGraphOptimizationLevel(options,ORT_ENABLE_EXTENDED));
   for(auto entry:{std::pair<const char*,const char*>{"session.intra_op.allow_spinning","1"},
                  {"session.inter_op.allow_spinning","0"},{"session.intra_op.spin_duration_us","10"},
                  {"session.intra_op.spin_backoff_max","8"},{"session.intra_op_thread_affinities","1;2;3"}})
    check(api->AddSessionConfigEntry(options,entry.first,entry.second));
   std::call_once(environment_once,[](){check(api->CreateEnv(ORT_LOGGING_LEVEL_ERROR,"residual-overlap",&residual_env));});
   check(api->CreateSessionFromArray(residual_env,data<uint8_t>(model),elements(model),options,&residual));
  }catch(...){api->ReleaseSessionOptions(options);throw;}
  api->ReleaseSessionOptions(options);
'''+text[end:]
text=text.replace('api->ReleaseOp(residual)','api->ReleaseSession(residual)')
old='check(api->InvokeOp(context,residual,values,9,&output,1))';assert text.count(old)==1
text=text.replace(old,'const char* input_names[]={"x"};const char* output_names[]={"y"};check(api->Run(residual,nullptr,input_names,values,1,output_names,1,&output))')
text=text.replace('return parallel(p)?12:3','return parallel(p)?13:3')
text=text.replace('"prototype.fpga.overlap"','"prototype.fpga.overlap.session"')
(target/'pointwise.cc').write_text(text)
print('Generated separate initialized CPU residual overlap runtime')
