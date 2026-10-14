"""Check whether CPU branch concurrency improves the reference baseline."""
import argparse,json,os,random,time
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
from chain_benchmark import ROOT,Frontend,read_audio,decode,make_session,sha,write_json,environment
from boundary_lut import transform
ap=argparse.ArgumentParser();ap.add_argument('--runs',type=int,default=30);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
model_path=ROOT/'research/fused/cpu-int8-cse.onnx';model,_=transform(onnx.load(model_path));boundary=ROOT/'software/latency/libboundary_lut.so'
policies=[{'threads':4,'spin':10,'level':'extended','execution':'sequential','inter_threads':1}]
policies += [{'threads':t,'spin':10,'level':level,'execution':'parallel','inter_threads':inter}
             for t,inter,level in ((2,2,'extended'),(3,2,'extended'),(4,2,'extended'),(4,3,'extended'),(3,2,'all'),(4,2,'all'))]
front=Frontend(ROOT/'research/export/citrinet-256-ls');vocab=(ROOT/'research/export/citrinet-256-ls/vocab.txt').read_text().splitlines()
audio=read_audio(ROOT/'research/eval/user-recording/speech.wav');affinity=os.sched_getaffinity(0);before=environment();rows=[];summaries=[]
try:
    runners=[]
    for config in policies:
        if config['execution']=='sequential':
            os.sched_setaffinity(0,{3});runners.append(make_session(model,config,[boundary]));continue
        os.sched_setaffinity(0,{0,1,2,3}) # Allow inter-op workers to use all cores.
        opt=ort.SessionOptions();opt.intra_op_num_threads=config['threads'];opt.inter_op_num_threads=config['inter_threads']
        opt.execution_mode=ort.ExecutionMode.ORT_PARALLEL;opt.log_severity_level=3
        opt.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED if config['level']=='extended' else ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        for key,value in [('session.intra_op.allow_spinning','1'),('session.inter_op.allow_spinning','0'),
                          ('session.intra_op.spin_duration_us','10'),('session.intra_op.spin_backoff_max','8')]:opt.add_session_config_entry(key,value)
        opt.add_session_config_entry('session.intra_op_thread_affinities',';'.join(str(i+1) for i in range(config['threads']-1)))
        opt.register_custom_ops_library(str(boundary))
        runners.append(ort.InferenceSession(onnx.shape_inference.infer_shapes(model).SerializeToString(),opt,providers=['CPUExecutionProvider']))
    os.sched_setaffinity(0,{3});rng=random.Random(202610122)
    for seconds in (.5,1,2.5):
        clip=np.ascontiguousarray(audio[:round(seconds*16000)])
        def call(index):
            start=time.perf_counter();x,n=front(clip);x=np.ascontiguousarray(x[:,:,:int(n[0])])
            logits,length=runners[index].run(None,{'features':x,'feature_lengths':n});text=decode(logits[0],length[0],vocab)
            return time.perf_counter()-start,logits,length,text
        _,expected,expected_length,text=call(0)
        for index in range(len(runners)):
            _,actual,length,actual_text=call(index);np.testing.assert_array_equal(actual,expected);np.testing.assert_array_equal(length,expected_length)
            assert actual_text==text
            for _ in range(3):call(index)
        context=[]
        for iteration in range(a.runs):
            order=list(range(len(runners)));rng.shuffle(order);values={}
            for index in order:
                time.sleep(.003);elapsed,_,length,actual_text=call(index);assert actual_text==text and int(length[0])==int(expected_length[0]);values[str(index)]=elapsed
            row={'context_seconds':seconds,'index':iteration,'order':order,'seconds':values};rows.append(row);context.append(row)
        candidates=[]
        for index,config in enumerate(policies):
            values=[r['seconds'][str(index)] for r in context]
            candidates.append({'index':index,'policy':config,'p50':float(np.median(values)),'p95':float(np.percentile(values,95))})
        candidates.sort(key=lambda c:c['p50']);summary={'context_seconds':seconds,'selected':candidates[0],'candidates':candidates}
        summaries.append(summary);print(json.dumps(summary),flush=True)
    write_json(a.out,{'complete':True,'timing_acceptance':False,'hardware_execution':False,'all_logits_bit_exact':True,
                      'scope':'Randomized CPU sequential/parallel policy screen','contexts':summaries,'runs':rows,
                      'source_sha256':sha(__file__),'model_sha256':sha(model_path),'boundary_library_sha256':sha(boundary),
                      'environment_before':before,'environment_after':environment()})
finally:os.sched_setaffinity(0,affinity)
