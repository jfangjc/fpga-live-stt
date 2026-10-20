"""Attribute CPU convolution time for the next larger-channel FPGA design.

Profiling is separate from latency acceptance. No speedup projection is proof.
"""
import argparse,json,os,sys
from pathlib import Path
import numpy as np
import onnxruntime as ort
from tail_benchmark import *
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
model_path=ROOT/'research/fused/cpu-int8-cse.onnx';model=onnx.load(model_path)
model,_=transform(model);model,records=tails(model)
arrays={v.name:onnx.numpy_helper.to_array(v) for v in model.graph.initializer}
metadata={n.name:{'name':n.name,'weight_shape':list(arrays[n.input[3]].shape),
                   'depthwise':next((onnx.helper.get_attribute_value(v) for v in n.attribute if v.name=='group'),1)>1,
                   'residual':'/res.' in n.name} for n in model.graph.node if n.op_type=='QLinearConv'}
front=Frontend(ROOT/'research/export/citrinet-256-ls');audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')
affinity=os.sched_getaffinity(0);contexts=[]
try:
    os.sched_setaffinity(0,{3})
    for seconds in (.5,1,2.5):
        opt=ort.SessionOptions();opt.intra_op_num_threads=4;opt.inter_op_num_threads=1
        opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL;opt.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
        opt.add_session_config_entry('session.intra_op_thread_affinities','1;2;3')
        opt.add_session_config_entry('session.intra_op.allow_spinning','1');opt.add_session_config_entry('session.intra_op.spin_duration_us','10')
        opt.add_session_config_entry('session.inter_op.allow_spinning','0');opt.enable_profiling=True
        opt.profile_file_prefix=str(a.out.with_suffix(''))+'_'+str(seconds)
        for path in ('software/latency/libboundary_lut.so','software/latency/libresidual_tail.so'):opt.register_custom_ops_library(str(ROOT/path))
        runner=ort.InferenceSession(model.SerializeToString(),opt,providers=['CPUExecutionProvider'])
        x,n=front(np.ascontiguousarray(audio[:round(seconds*16000)]));x=np.ascontiguousarray(x[:,:,:int(n[0])]);feed={'features':x,'feature_lengths':n}
        for _ in range(15):runner.run(None,feed)
        path=Path(runner.end_profiling());events=json.loads(path.read_text());collected={}
        for event in events:
            name=event.get('name','')
            if event.get('cat')!='Node' or not name.endswith('_kernel_time'):continue
            name=name[:-len('_kernel_time')]
            if name in metadata:collected.setdefault(name,[]).append(event['dur'])
        rows=[metadata[name]|{'median_profile_microseconds':float(np.median(values[5:])),'samples':len(values)} for name,values in collected.items()]
        rows.sort(key=lambda r:r['median_profile_microseconds'],reverse=True)
        contexts.append({'seconds':seconds,'rows':rows,'profile_path':str(path),'profile_sha256':sha(path)})
        print(json.dumps({'seconds':seconds,'top_convolutions':rows[:12]}),flush=True)
finally:os.sched_setaffinity(0,affinity)
write_json(a.out,{'complete':True,'hardware_execution':False,'timing_acceptance':False,'source_sha256':sha(__file__),
                 'cpu_model_sha256':sha(model_path),'contexts':contexts,'note':'ORT event attribution; not full-path latency or a speedup prediction'})
