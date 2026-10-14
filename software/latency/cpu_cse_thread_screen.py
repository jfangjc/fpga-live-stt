"""Select CPU thread policy after exact graph common-subexpression elimination."""
import argparse,json,sys,time,random
from pathlib import Path
import numpy as np
import onnx
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
from probe import session
from common import Frontend,read_audio,decode,sha,identity,environment,write_json

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--contexts',type=float,nargs='+',default=[.5,1,2,4,8,10])
    p.add_argument('--threads',type=int,nargs='+',default=[1,2,4])
    p.add_argument('--runs',type=int,default=50)
    p.add_argument('--wav',type=Path,default=ROOT/'research/eval/user-recording/speech.wav')
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.runs<20 or min(a.contexts)<.02 or not set(a.threads)<={1,2,4}:p.error('Invalid screen configuration')
    model_path=ROOT/'research/fused/cpu-int8-cse.onnx';directory=ROOT/'research/export/citrinet-256-ls'
    proof=json.loads(model_path.with_suffix('.json').read_text())
    assert sha(model_path)==proof['model_sha256'] and identity(directory)==proof['source_identity']
    model=onnx.load(str(model_path));runners={};initialization={}
    for threads in a.threads:
        start=time.perf_counter();runners[threads]=session(model,threads=threads)
        initialization[threads]=time.perf_counter()-start
    frontend=Frontend(directory);vocab=(directory/'vocab.txt').read_text().splitlines();full=read_audio(a.wav)
    if max(a.contexts)>len(full)/16000+1e-9:raise ValueError('Context exceeds source')
    rng=random.Random(10102026);rows=[];summary=[]
    def call(threads,audio):
        start=time.perf_counter();x,n=frontend(audio);f=time.perf_counter()
        logits,length=runners[threads].run(None,{'features':x,'feature_lengths':n});m=time.perf_counter()
        text=decode(logits[0],length[0],vocab);end=time.perf_counter()
        assert np.all(np.isfinite(logits))
        return {'seconds':end-start,'frontend_seconds':f-start,'model_seconds':m-f,'decode_seconds':end-m,
                'text':text,'encoded_length':int(length[0])},logits,length
    for seconds in sorted(set(a.contexts)):
        audio=full[:round(seconds*16000)];reference=None;bit_parity=True;max_logit_difference=0.
        for threads in a.threads:
            first,l,n=call(threads,audio)
            if reference is None:reference=(l,n)
            else:
                np.testing.assert_array_equal(n,reference[1])
                assert l.shape==reference[0].shape
                bit_parity &= np.array_equal(l,reference[0])
                max_logit_difference=max(max_logit_difference,float(np.max(np.abs(l-reference[0]))))
                np.testing.assert_allclose(l,reference[0],rtol=1e-5,atol=1e-4)
            for _ in range(3):call(threads,audio)
        pairs=[];env=environment()
        for i in range(a.runs):
            order=list(a.threads);rng.shuffle(order);pair={}
            for threads in order:pair[str(threads)]=call(threads,audio)[0]
            assert len({v['text'] for v in pair.values()})==1
            pairs.append(pair);rows.append({'context_seconds':seconds,'repeat':i,'order':order,'results':pair})
        c={'context_seconds':seconds,'cpu_bit_parity_between_thread_policies':bool(bit_parity),'max_logit_difference_between_policies':max_logit_difference,'environment_before':env,
           'environment_after':environment(),'policies':{}}
        for threads in a.threads:
            values=np.array([v[str(threads)]['seconds'] for v in pairs])
            c['policies'][str(threads)]={'p50':float(np.median(values)),'p95':float(np.percentile(values,95)),
                'model_p50':float(np.median([v[str(threads)]['model_seconds'] for v in pairs])),
                'frontend_p50':float(np.median([v[str(threads)]['frontend_seconds'] for v in pairs]))}
        c['fastest_p50_threads']=min(a.threads,key=lambda t:c['policies'][str(t)]['p50'])
        idx=np.random.default_rng(199026).integers(0,a.runs,(10000,a.runs))
        c['paired_mean_saving_vs_four_95ci_seconds']={str(t):np.percentile(
            np.array([v['4']['seconds']-v[str(t)]['seconds'] for v in pairs])[idx].mean(1),[2.5,97.5]).tolist()
            for t in a.threads if t!=4 and 4 in a.threads}
        summary.append(c)
        write_json(a.out,{'hardware_fpga_execution':False,'scope':'CPU thread screen; resident memory-input frontend/model/decoder',
            'complete':len(summary)==len(set(a.contexts)),'runs':a.runs,'worker_spinning':False,
            'initialization_seconds':initialization,'model_sha256':sha(model_path),'audio_sha256':sha(a.wav),
            'runner_sha256':sha(__file__),'contexts':summary,'triple_runs':rows})
        print(seconds,c['policies'],'best',c['fastest_p50_threads'],flush=True)
if __name__=='__main__':main()
