"""Kick FPGA DMA on the calling thread; overlap CPU residuals in a worker."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1];source=ROOT/'software/ort_fpga_overlap_session';target=ROOT/'software/ort_fpga_pipeline'
target.mkdir(parents=True,exist_ok=True)
for name in ('qnc.h','qnc_transport.c','build.sh'):shutil.copyfile(source/name,target/name)
shutil.copytree(source/'include',target/'include',dirs_exist_ok=True)
text=(source/'pointwise.cc').read_text()
text=text.replace('double device_seconds=0;','double residual_duration=0;')
old='try{engine.compute(context);}catch(...){error=std::current_exception();}';assert text.count(old)==1
text=text.replace(old,'try{cpu_compute(context);}catch(...){error=std::current_exception();}')
text=text.replace('device_seconds=duration;finished=true','residual_duration=duration;finished=true')
position=text.index(' void work(){')
text=text[:position]+r''' void cpu_compute(OrtKernelContext* context){
  const OrtValue* value=input(context,0);auto dims=shape(value);dims[1]=channels;dims[2]=(dims[2]+stride-1)/stride;
  OrtValue* output=nullptr;check(api->KernelContext_GetOutput(context,0,dims.data(),3,&output));
  const char* inputs[]={"x"};const char* outputs[]={"y"};check(api->Run(residual,nullptr,inputs,&value,1,outputs,1,&output));
 }
'''+text[position:]
old='try{const char* input_names[]={"x"};const char* output_names[]={"y"};check(api->Run(residual,nullptr,input_names,values,1,output_names,1,&output));}catch(...){cpu_failure=std::current_exception();}'
assert text.count(old)==1
text=text.replace(old,'try{engine.compute(context);}catch(...){cpu_failure=std::current_exception();}')
text=text.replace('duration=device_seconds','duration=residual_duration')
text=text.replace('overlap_profile.residual_seconds+=seconds(cpu_start,cpu_end);overlap_profile.device_seconds+=duration;',
                  'overlap_profile.residual_seconds+=duration;overlap_profile.device_seconds+=seconds(cpu_start,cpu_end);')
text=text.replace('prototype.fpga.overlap.session','prototype.fpga.pipeline')
text=text.replace('cpu_failure','fpga_failure').replace('device_failure','cpu_failure')
text=text.replace('cpu_start','fpga_start').replace('cpu_end','fpga_end')
(target/'pointwise.cc').write_text(text)
graph=(source/'session_graph.py').read_text().replace('prototype.fpga.overlap.session','prototype.fpga.pipeline')
(target/'pipeline_graph.py').write_text(graph)
print('Generated isolated FPGA-first CPU-residual pipeline; numerical kernels unchanged')
