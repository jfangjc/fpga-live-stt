"""Pin independent CPU residual work away from the FPGA caller's core."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1];source=ROOT/'software/ort_fpga_pipeline';target=ROOT/'software/ort_fpga_pipeline_pinned'
target.mkdir(parents=True,exist_ok=True)
for name in ('qnc.h','qnc_transport.c','build.sh'):shutil.copyfile(source/name,target/name)
shutil.copytree(source/'include',target/'include',dirs_exist_ok=True)
text=(source/'pointwise.cc').read_text().replace('#include <thread>','#include <thread>\n#include <pthread.h>\n#include <sched.h>')
text=text.replace('bool stopping=false,pending=false,finished=true;',
                  'bool stopping=false,pending=false,finished=true,worker_ready=false;int affinity_status=0;')
text=text.replace('int64_t stride=0,channels=0;','int64_t stride=0,channels=0,res_threads=0;')
text=text.replace('int model_constant=0;const OrtValue* model=nullptr;',
                  'check(api->KernelInfoGetAttribute_int64(info,"res_threads",&res_threads));require(res_threads>=1&&res_threads<=4,"Invalid residual thread count");\n  int model_constant=0;const OrtValue* model=nullptr;')
text=text.replace('SetIntraOpNumThreads(options,4)','SetIntraOpNumThreads(options,int(res_threads))')
text=text.replace(',{"session.intra_op_thread_affinities","1;2;3"}','')
needle='   std::call_once(environment_once'
position=text.index(needle)
text=text[:position]+'''   if(res_threads>1){std::string affinity;
    for(int64_t i=1;i<res_threads;i++){if(i>1)affinity+=";";affinity+=std::to_string(i+1);}
    check(api->AddSessionConfigEntry(options,"session.intra_op_thread_affinities",affinity.c_str()));
   }
'''+text[position:]
old='try{worker=std::thread([this](){work();});}catch(...){api->ReleaseSession(residual);throw;}'
new='''try{worker=std::thread([this](){work();});
   std::unique_lock<std::mutex> lock(work_mutex);work_cv.wait(lock,[this](){return worker_ready;});
   require(affinity_status==0,"Cannot pin CPU residual worker to core 0");
  }catch(...){if(worker.joinable()){{std::lock_guard<std::mutex> lock(work_mutex);stopping=true;work_cv.notify_all();}worker.join();}api->ReleaseSession(residual);throw;}'''
assert text.count(old)==1;text=text.replace(old,new)
old='void work(){\n  std::unique_lock<std::mutex> lock(work_mutex);'
new='''void work(){
  cpu_set_t affinity;CPU_ZERO(&affinity);CPU_SET(0,&affinity);
  int result=pthread_setaffinity_np(pthread_self(),sizeof(affinity),&affinity);
  std::unique_lock<std::mutex> lock(work_mutex);affinity_status=result;worker_ready=true;work_cv.notify_all();if(result)return;'''
assert text.count(old)==1;text=text.replace(old,new)
text=text.replace('prototype.fpga.pipeline','prototype.fpga.pipeline.pinned')
(target/'pointwise.cc').write_text(text)
graph=(source/'pipeline_graph.py').read_text().replace('prototype.fpga.pipeline','prototype.fpga.pipeline.pinned')
graph=graph.replace("node.domain='prototype.fpga.pipeline.pinned'","node.domain='prototype.fpga.pipeline.pinned'\n        if node.op_type in ('FpgaResidualChain','OracleResidualChain'):node.attribute.append(helper.make_attribute('res_threads',3))")
(target/'pinned_graph.py').write_text(graph)
print('Generated CPU-core-0 residual worker with configurable nested thread count')
