"""Randomized CPU screen of short worker spin windows, with pinned workers."""
import argparse
import json
import os
from pathlib import Path
import random
import sys
import time
import numpy as np
import onnx
import onnxruntime as ort
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
from common import Frontend as OriginalFrontend, read_audio, decode, sha, identity, environment, write_json

class Frontend(OriginalFrontend):
    def __call__(self,audio):
        x,n=super().__call__(audio)
        return np.ascontiguousarray(x[:,:,:int(n[0])]),n


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--spins',nargs='+',type=int,default=[0,10,25,50,100,250,500])
    ap.add_argument('--contexts',nargs='+',type=float,default=[.5,1])
    ap.add_argument('--runs',type=int,default=30)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    assert a.runs>=20 and min(a.spins)>=0 and max(a.spins)<=1000
    assert sorted(os.sched_getaffinity(0))==[0,1,2,3]
    os.sched_setaffinity(0,{3})
    path=ROOT/'research/fused/cpu-int8-cse.onnx'
    directory=ROOT/'research/export/citrinet-256-ls'
    proof=json.loads(path.with_suffix('.json').read_text())
    assert sha(path)==proof['model_sha256'] and identity(directory)==proof['source_identity']
    graph=onnx.shape_inference.infer_shapes(onnx.load(str(path))).SerializeToString()
    runners={}; setup={}
    for spin in sorted(set(a.spins)):
        opt=ort.SessionOptions(); opt.intra_op_num_threads=4; opt.inter_op_num_threads=1
        opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        opt.add_session_config_entry('session.intra_op_thread_affinities','1;2;3')
        opt.add_session_config_entry('session.intra_op.allow_spinning','1' if spin else '0')
        opt.add_session_config_entry('session.inter_op.allow_spinning','0')
        opt.add_session_config_entry('session.intra_op.spin_duration_us',str(spin))
        opt.add_session_config_entry('session.intra_op.spin_backoff_max','8')
        start=time.perf_counter(); runners[spin]=ort.InferenceSession(graph,opt,providers=['CPUExecutionProvider'])
        setup[str(spin)]=time.perf_counter()-start
    frontend=Frontend(directory); vocab=(directory/'vocab.txt').read_text().splitlines()
    full=read_audio(ROOT/'research/eval/user-recording/speech.wav')
    rng=random.Random(101027); summary=[]; rows=[]
    for seconds in sorted(set(a.contexts)):
        assert .02<=seconds<=len(full)/16000
        audio=np.ascontiguousarray(full[:round(seconds*16000)])
        x,n=frontend(audio); reference=None
        for spin,runner in runners.items():
            result=runner.run(None,{'features':x,'feature_lengths':n})
            if reference is None: reference=result
            else:
                for left,right in zip(result,reference): np.testing.assert_array_equal(left,right)
        def call(spin):
            time.sleep(.003); start=time.perf_counter(); x,n=frontend(audio); f=time.perf_counter()
            y,enc=runners[spin].run(None,{'features':x,'feature_lengths':n}); m=time.perf_counter()
            text=decode(y[0],enc[0],vocab); end=time.perf_counter()
            return {'seconds':end-start,'frontend_seconds':f-start,'model_seconds':m-f,'decode_seconds':end-m,'text':text}
        for _ in range(3):
            for spin in runners: call(spin)
        pairs=[]; before=environment()
        for i in range(a.runs):
            order=list(runners); rng.shuffle(order)
            pair={str(spin):call(spin) for spin in order}
            assert len({r['text'] for r in pair.values()})==1
            pairs.append(pair); rows.append({'context_seconds':seconds,'repeat':i,'order':order,'results':pair})
        policies={str(spin):{'p50':float(np.median([r[str(spin)]['seconds'] for r in pairs])),
                            'p95':float(np.percentile([r[str(spin)]['seconds'] for r in pairs],95))} for spin in runners}
        summary.append({'context_seconds':seconds,'policies':policies,'all_logits_bit_exact':True,
                        'environment_before':before,'environment_after':environment(),
                        'fastest_p50_spin_us':min(runners,key=lambda s:policies[str(s)]['p50'])})
        write_json(a.out,{'complete':len(summary)==len(set(a.contexts)),'hardware_execution':False,'cpu_threads':4,
                         'main_core':3,'worker_cores':[0,1,2],'idle_between_calls_seconds':.003,'runs':a.runs,
                         'feature_padding_policy':'trim_to_valid','model_sha256':sha(path),'source_sha256':sha(__file__),'initialization_seconds':setup,
                         'contexts':summary,'paired_runs':rows})
        print(seconds,policies,flush=True)


if __name__=='__main__': main()
