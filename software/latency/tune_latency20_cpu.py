"""Screen CPU policies fairly after boundary fusion; exclude startup from timing."""
import argparse,json,os,random,sys,time
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
from common import Frontend,read_audio,decode,sha,write_json,environment
from boundary_lut import transform
ap=argparse.ArgumentParser();ap.add_argument('--runs',type=int,default=40);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
model_path=ROOT/'research/fused/cpu-int8-cse.onnx';original=onnx.load(model_path);fused,records=transform(original)
library=ROOT/'software/latency/libboundary_lut.so'
policies=[{'graph':'original','threads':4,'spin':10,'level':'all'}]
policies += [{'graph':'boundary','threads':t,'spin':s,'level':'all'} for t,s in ((1,0),(2,0),(2,10),(3,10),(4,0),(4,10))]
policies += [{'graph':'boundary','threads':4,'spin':10,'level':'extended'}]
front=Frontend(ROOT/'research/export/citrinet-256-ls');vocab=(ROOT/'research/export/citrinet-256-ls/vocab.txt').read_text().splitlines()
audio=read_audio(ROOT/'research/eval/user-recording/speech.wav');affinity=os.sched_getaffinity(0)
before=environment();rows=[];summaries=[]
try:
    os.sched_setaffinity(0,{3})
    runners=[]
    for cfg in policies:
        opt=ort.SessionOptions();opt.intra_op_num_threads=cfg['threads'];opt.inter_op_num_threads=1
        opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        opt.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL if cfg['level']=='all' else ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
        opt.add_session_config_entry('session.intra_op.allow_spinning','1' if cfg['spin'] else '0')
        opt.add_session_config_entry('session.inter_op.allow_spinning','0')
        opt.add_session_config_entry('session.intra_op.spin_duration_us',str(cfg['spin']))
        opt.add_session_config_entry('session.intra_op.spin_backoff_max','8')
        if cfg['threads']>1:opt.add_session_config_entry('session.intra_op_thread_affinities',';'.join(str(i+1) for i in range(cfg['threads']-1)))
        if cfg['graph']=='boundary':opt.register_custom_ops_library(str(library))
        graph=original if cfg['graph']=='original' else fused
        runners.append(ort.InferenceSession(graph.SerializeToString(),opt,providers=['CPUExecutionProvider']))
    rng=random.Random(20261012)
    for seconds in (.5,1,2.5):
        clip=np.ascontiguousarray(audio[:round(seconds*16000)])
        def call(index):
            start=time.perf_counter();x,n=front(clip);x=np.ascontiguousarray(x[:,:,:int(n[0])])
            logits,length=runners[index].run(None,{'features':x,'feature_lengths':n})
            text=decode(logits[0],length[0],vocab)
            return time.perf_counter()-start,logits,length,text
        _,expected,expected_length,text=call(0)
        for index in range(len(runners)):
            _,actual,length,actual_text=call(index)
            np.testing.assert_array_equal(actual,expected);np.testing.assert_array_equal(length,expected_length)
            assert text==actual_text
            for _ in range(3):call(index)
        context_rows=[]
        for i in range(a.runs):
            order=list(range(len(runners)));rng.shuffle(order);values={}
            for index in order:
                time.sleep(.003);elapsed,_,length,actual_text=call(index)
                assert actual_text==text and int(length[0])==int(expected_length[0]);values[str(index)]=elapsed
            row={'context_seconds':seconds,'index':i,'order':order,'seconds':values};rows.append(row);context_rows.append(row)
        candidates=[]
        for index,cfg in enumerate(policies):
            samples=[r['seconds'][str(index)] for r in context_rows]
            candidates.append({'index':index,'policy':cfg,'p50':float(np.median(samples)),'p95':float(np.percentile(samples,95))})
        candidates.sort(key=lambda r:r['p50']);summary={'context_seconds':seconds,'candidates':candidates,'selected':candidates[0]}
        summaries.append(summary);print(json.dumps(summary),flush=True)
finally:os.sched_setaffinity(0,affinity)
write_json(a.out,{'complete':True,'hardware_execution':False,'timing_acceptance':False,'runs':a.runs,
                 'scope':'Randomized CPU-only scheduling screen; confirmation required',
                 'contexts':summaries,'runs_data':rows,'source_sha256':sha(__file__),
                 'model_sha256':sha(model_path),'boundary_library_sha256':sha(library),
                 'environment_before':before,'environment_after':environment(),'all_logits_bit_exact':True})
