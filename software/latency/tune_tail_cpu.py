"""Rescreen common tail fusion against the previously strongest CPU policy."""
import argparse,json,os,random,time
import numpy as np
from tail_benchmark import *
from boundary_lut import transform as boundary
ap=argparse.ArgumentParser();ap.add_argument('--runs',type=int,default=40);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
path=ROOT/'research/fused/cpu-int8-cse.onnx';original=onnx.load(path)
boundary_graph,_=boundary(original);tail_graph,records=tails(boundary_graph)
proof=json.loads((ROOT/'reports/fused/residual_tail_validation.json').read_text());assert proof['complete'] and proof['all_bit_exact']
lib=ROOT/'software/latency/libresidual_tail.so';assert sha(lib)==proof['library_sha256']
policies=[{'graph':'boundary','threads':4,'spin':10,'level':'extended'}]
policies += [{'graph':'tail','threads':t,'spin':s,'level':level} for t,s,level in
             ((1,0,'all'),(2,10,'all'),(3,10,'all'),(4,0,'all'),(4,10,'all'),(4,10,'extended'))]
frontend=Frontend(ROOT/'research/export/citrinet-256-ls');vocab=(ROOT/'research/export/citrinet-256-ls/vocab.txt').read_text().splitlines()
audio=read_audio(ROOT/'research/eval/user-recording/speech.wav');affinity=os.sched_getaffinity(0);before=environment();rows=[];contexts=[]
try:
    os.sched_setaffinity(0,{3})
    runners=[make_session(boundary_graph if c['graph']=='boundary' else tail_graph,c,[ROOT/'software/latency/libboundary_lut.so']) for c in policies]
    rng=random.Random(2026101207)
    for seconds in (.5,1,2.5):
        clip=np.ascontiguousarray(audio[:round(seconds*16000)])
        def call(index):
            start=time.perf_counter();x,n=frontend(clip);x=np.ascontiguousarray(x[:,:,:int(n[0])])
            logits,length=runners[index].run(None,{'features':x,'feature_lengths':n});text=decode(logits[0],length[0],vocab)
            return time.perf_counter()-start,logits,length,text
        _,reference,length,text=call(0)
        for index in range(len(runners)):
            _,actual,actual_length,actual_text=call(index);np.testing.assert_array_equal(actual,reference);np.testing.assert_array_equal(actual_length,length)
            assert actual_text==text
            for _ in range(3):call(index)
        samples=[]
        for i in range(a.runs):
            order=list(range(len(runners)));rng.shuffle(order);values={}
            for index in order:
                time.sleep(.003);elapsed,_,actual_length,actual_text=call(index);assert actual_text==text and int(actual_length[0])==int(length[0]);values[str(index)]=elapsed
            row={'context_seconds':seconds,'index':i,'order':order,'seconds':values};samples.append(row);rows.append(row)
        candidates=[{'policy':c,'index':i,'p50':float(np.median([r['seconds'][str(i)] for r in samples])),
                    'p95':float(np.percentile([r['seconds'][str(i)] for r in samples],95))} for i,c in enumerate(policies)]
        selected=min(candidates,key=lambda c:c['p50']);contexts.append({'context_seconds':seconds,'candidates':candidates,'selected':selected})
        print(json.dumps(contexts[-1]),flush=True)
finally:os.sched_setaffinity(0,affinity)
write_json(a.out,{'complete':True,'hardware_execution':False,'all_logits_bit_exact':True,'contexts':contexts,'runs':rows,
                 'model_sha256':sha(path),'boundary_library_sha256':sha(ROOT/'software/latency/libboundary_lut.so'),
                 'residual_tail_library_sha256':sha(lib),'source_sha256':sha(__file__),'environment_before':before,'environment_after':environment()})
