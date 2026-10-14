"""Measure frontend BLAS allocation; require bit exact features for every policy."""
import ctypes,json,os,random,time
from pathlib import Path
import numpy as np
from chain_benchmark import ROOT,Frontend,read_audio,sha,write_json,environment,make_session,onnx,corpus
maps=Path('/proc/self/maps').read_text().splitlines()
paths=sorted({r.split()[-1] for r in maps if 'openblas' in r.lower() and r.split()[-1].startswith('/')})
assert len(paths)==1,paths
lib=ctypes.CDLL(paths[0]);found=None
for prefix,suffix in (('scipy_openblas_','64_'),('openblas_','64_'),('openblas_',''),('scipy_openblas_','')):
    try:
        get=getattr(lib,prefix+'get_num_threads'+suffix);set_threads=getattr(lib,prefix+'set_num_threads'+suffix)
        found=(get,set_threads);break
    except AttributeError:pass
assert found,'OpenBLAS thread API unavailable'
get,set_threads=found;get.restype=ctypes.c_int;set_threads.argtypes=[ctypes.c_int]
previous=get();affinity=os.sched_getaffinity(0);before=environment()
audio=read_audio(ROOT/'research/eval/user-recording/speech.wav');frontend=Frontend(ROOT/'research/export/citrinet-256-ls')
rows=[];contexts=[];maximum_feature_difference=0.;full_model_cases=[]
try:
    os.sched_setaffinity(0,{3});rng=random.Random(20261012)
    for seconds in (.5,1,2.5):
        clip=np.ascontiguousarray(audio[:round(seconds*16000)]);set_threads(previous);expected=frontend(clip)
        policies=sorted({1,2,3,4,previous});samples={str(p):[] for p in policies}
        for iteration in range(50):
            order=policies[:];rng.shuffle(order)
            for count in order:
                set_threads(count);assert get()==count
                start=time.perf_counter();actual=frontend(clip);elapsed=time.perf_counter()-start
                np.testing.assert_array_equal(actual[1],expected[1])
                np.testing.assert_allclose(actual[0],expected[0],atol=1e-5,rtol=0)
                maximum_feature_difference=max(maximum_feature_difference,float(np.max(np.abs(actual[0]-expected[0]))))
                samples[str(count)].append(elapsed)
            rows.append({'context_seconds':seconds,'index':iteration,'order':order,'seconds':{k:v[-1] for k,v in samples.items()}})
        candidates=[{'threads':int(k),'p50':float(np.median(v)),'p95':float(np.percentile(v,95))} for k,v in samples.items()]
        contexts.append({'context_seconds':seconds,'candidates':candidates,'selected':min(candidates,key=lambda c:c['p50'])})
        print(json.dumps(contexts[-1]),flush=True)
    runner=make_session(onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx'),{'threads':4,'spin':10,'level':'extended'})
    clips=[]
    for folder in ('user-recording','librispeech-mini','user-stress-ac'):
        clips+=corpus(ROOT/'research/eval'/folder/'evaluation.jsonl',('evaluation','test'))
    for clip in clips:
        audio=read_audio(clip['path'])
        for seconds in (.25,.5,1,2):
            waveform=np.ascontiguousarray(audio[:round(seconds*16000)]);set_threads(previous);expected=frontend(waveform)
            ref=runner.run(None,{'features':np.ascontiguousarray(expected[0][:,:,:int(expected[1][0])]),'feature_lengths':expected[1]})
            for count in policies:
                set_threads(count);actual=frontend(waveform)
                np.testing.assert_allclose(actual[0],expected[0],atol=1e-5,rtol=0)
                outputs=runner.run(None,{'features':np.ascontiguousarray(actual[0][:,:,:int(actual[1][0])]),'feature_lengths':actual[1]})
                for a,b in zip(outputs,ref):np.testing.assert_array_equal(a,b)
                full_model_cases.append({'id':clip['id'],'seconds':seconds,'threads':count,'full_cpu_outputs_bit_exact':True,
                                         'maximum_feature_difference':float(np.max(np.abs(actual[0]-expected[0])))})
finally:set_threads(previous);os.sched_setaffinity(0,affinity)
write_json(ROOT/'reports/fused/frontend_thread_screen.json',{'complete':True,'all_features_bit_exact':maximum_feature_difference==0,'hardware_execution':False,
           'feature_absolute_tolerance':1e-5,'maximum_feature_difference':maximum_feature_difference,'all_cpu_outputs_bit_exact':True,'full_model_cases':full_model_cases,
           'previous_threads':previous,'openblas_library':paths[0],'contexts':contexts,'runs':rows,
           'source_sha256':sha(__file__),'frontend_source_sha256':sha(ROOT/'software/model-tools/citrinet_cpu.py'),
           'environment_before':before,'environment_after':environment()})
