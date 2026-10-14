"""Recheck leading valid-frame CPU policies in isolation after FPGA timings."""
import argparse,gc,json,os,sys,time
from pathlib import Path
import numpy as np
import onnx
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
from common import read_audio,decode,sha,write_json,environment
from frontend_valid_frames import ValidFrameFrontend
from boundary_lut import transform as boundary
from residual_tail import transform as tails
from se_pool import transform as pool
from chain_benchmark import make_session
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
screen_path=ROOT/'reports/fused/valid_frame_cpu_policy.json';screen=json.loads(screen_path.read_text())
assert screen['complete'] and screen['candidate_count']==64 and screen['all_warm_logits_bit_exact']
model_path=ROOT/'research/fused/cpu-int8-cse.onnx';assert sha(model_path)==screen['model_sha256']
original=onnx.load(model_path);tail,_=tails(boundary(original)[0]);pooled,_=pool(tail)
directory=ROOT/'research/export/citrinet-256-ls';frontend=ValidFrameFrontend(directory)
vocab=(directory/'vocab.txt').read_text().splitlines();audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')
affinity=os.sched_getaffinity(0);contexts=[];before=environment()
try:
    os.sched_setaffinity(0,{3})
    for context in screen['contexts']:
        seconds=context['context_seconds'];clip=np.ascontiguousarray(audio[:round(seconds*16000)])
        candidates=sorted(context['candidates'],key=lambda c:c['p50'])[:4]
        # Also explicitly recheck the previously strongest native maskfast CPU.
        prior={'graph':'pool','threads':4,'spin':10,'level':'extended','tail_impl':'maskfast'}
        if all(c['policy']!=prior for c in candidates):candidates.append(next(c for c in context['candidates'] if c['policy']==prior))
        x,n=frontend(clip);reference=make_session(original,{'threads':4,'spin':10,'level':'extended'})
        expected,length=reference.run(None,{'features':x,'feature_lengths':n});del reference;gc.collect()
        policies=[]
        for candidate in candidates:
            config=candidate['policy'];libraries=[ROOT/'software/latency/libboundary_lut.so',ROOT/'software/latency'/('libresidual_tail_maskfast.so' if config['tail_impl']=='maskfast' else 'libresidual_tail.so')]
            if config['graph']=='pool':libraries.append(ROOT/'software/latency/libse_pool.so')
            runner=make_session(pooled if config['graph']=='pool' else tail,config,libraries);samples=[]
            for i in range(110):
                time.sleep(.003);start=time.perf_counter();x,n=frontend(clip)
                actual,m=runner.run(None,{'features':x,'feature_lengths':n});text=decode(actual[0],m[0],vocab);elapsed=time.perf_counter()-start
                np.testing.assert_array_equal(actual,expected);np.testing.assert_array_equal(m,length)
                if i>=10:samples.append(elapsed)
            policies.append({'policy':config,'cpu_p50':float(np.median(samples)),'cpu_p95':float(np.percentile(samples,95)),'seconds':samples,'all_logits_bit_exact':True})
            del runner;gc.collect()
        context_result={'context_seconds':seconds,'policies':policies,'fastest':min(policies,key=lambda c:c['cpu_p50'])}
        contexts.append(context_result);print(json.dumps({'seconds':seconds,'fastest':{k:v for k,v in context_result['fastest'].items() if k!='seconds'}}),flush=True)
finally:os.sched_setaffinity(0,affinity)
write_json(a.out,{'complete':True,'hardware_execution':False,'fpga_session_loaded':False,'runs_per_policy':100,'contexts':contexts,'screen_sha256':sha(screen_path),'source_sha256':sha(__file__),'frontend_sha256':sha(ROOT/'software/latency/frontend_valid_frames.py'),'cpu_model_sha256':sha(model_path),'environment_before':before,'environment_after':environment()})
