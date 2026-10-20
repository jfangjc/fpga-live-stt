"""Compare the complete physical pair with its optimized extracted CPU subgraph.

Input capture/session creation are outside warm block timing. All warm FPGA
transfers and synchronization are inside it; first weight loading is separate.
"""
import argparse,ctypes,json,os,random,sys,time
from pathlib import Path
import numpy as np
import onnx
from onnx.utils import Extractor
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
from probe import stats
from common import Frontend,read_audio,sha,expose,write_json,identity,environment
from graph import candidate


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seconds',type=float,default=.5);ap.add_argument('--runs',type=int,default=200)
    ap.add_argument('--cpu-only',action='store_true')
    ap.add_argument('--threads',type=int,choices=(1,2,4),default=4)
    ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();assert a.runs>=20
    model_path=ROOT/'research/fused/cpu-int8-cse.onnx';model=onnx.shape_inference.infer_shapes(onnx.load(str(model_path)))
    proof=json.loads(model_path.with_suffix('.json').read_text());directory=ROOT/'research/export/citrinet-256-ls'
    assert sha(model_path)==proof['model_sha256'] and identity(directory)==proof['source_identity']
    nodes={n.name:n for n in model.graph.node}
    dw=nodes['/encoder/encoder.1/mconv.5/conv/Conv_quant'];pw=nodes['/encoder/encoder.1/mconv.6/conv/Conv_quant']
    inputs=[dw.input[0],nodes['/encoder/encoder.1/mconv.6/Where'].input[0]]
    original_affinity=os.sched_getaffinity(0);os.sched_setaffinity(0,{3})
    spin=10 if a.seconds>=1 else 0
    library=Path(__file__).with_name('libort_fpga.so');lib=ctypes.CDLL(str(library.resolve()))
    def session(g,custom=False):
        opt=ort.SessionOptions();opt.intra_op_num_threads=a.threads;opt.inter_op_num_threads=1
        opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        for key,val in [('session.intra_op.allow_spinning','1' if spin else '0'),
                        ('session.inter_op.allow_spinning','0'),('session.intra_op.spin_duration_us',str(spin)),
                        ('session.intra_op.spin_backoff_max','8')]:
            opt.add_session_config_entry(key,val)
        if a.threads>1:opt.add_session_config_entry('session.intra_op_thread_affinities',';'.join(str(i+1) for i in range(a.threads-1)))
        if custom:opt.register_custom_ops_library(str(library.resolve()))
        return ort.InferenceSession(g.SerializeToString(),opt,providers=['CPUExecutionProvider'])
    try:
        capture=session(expose(model,inputs));audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')
        x,n=Frontend(directory)(audio[:round(a.seconds*16000)]);x=np.ascontiguousarray(x[:,:,:int(n[0])])
        values=capture.run(inputs,{'features':x,'feature_lengths':n});feed=dict(zip(inputs,values));del capture
        block=Extractor(model).extract_model(inputs,list(pw.output));onnx.checker.check_model(block)
        if a.cpu_only:
            cpu=session(block)
            for _ in range(5):cpu.run(None,feed)
            durations=[]
            for _ in range(a.runs):
                time.sleep(.003);start=time.perf_counter();cpu.run(None,feed)
                durations.append(time.perf_counter()-start)
            write_json(a.out,{'complete':True,'hardware_execution':False,'context_seconds':a.seconds,
                             'scope':'Optimized extracted CPU pair; no physical or whole-model speed claim',
                             'runs':a.runs,'cpu_p50':float(np.median(durations)),
                             'cpu_threads':a.threads,'main_core':3,'spin_duration_us':spin,
                             'cpu_p95':float(np.percentile(durations,95)),'seconds':durations,
                             'model_sha256':sha(model_path),'source_sha256':sha(__file__),
                             'input_shapes':{k:list(v.shape) for k,v in feed.items()}})
            print('CPU block',np.median(durations),flush=True)
            return
        graph=candidate(block);oracle=candidate(block,oracle=True)
        runners={'cpu':session(block),'fpga':session(graph,True),'oracle':session(oracle,True)}
        def call(kind):
            time.sleep(.003);before=stats(lib);start=time.perf_counter();y=runners[kind].run(None,feed)[0]
            elapsed=time.perf_counter()-start;delta={k:v-before[k] for k,v in stats(lib).items()}
            assert delta['physical_calls']==(kind=='fpga') and delta['oracle_calls']==(kind=='oracle')
            return elapsed,y,delta
        first,actual,cold=call('fpga');_,expected,_=call('oracle');np.testing.assert_array_equal(actual,expected)
        for _ in range(5):call('cpu');call('fpga')
        rng=random.Random(11102026);rows=[];env=environment()
        for i in range(a.runs):
            order=['cpu','fpga'];rng.shuffle(order);row={'order':order,'index':i,'seconds':{}}
            for kind in order:
                elapsed,_,delta=call(kind);row['seconds'][kind]=elapsed
                if kind=='fpga':
                    assert delta['ioctls']==1 and delta['loads']==0;row['counters']=delta
            rows.append(row)
        c=np.array([r['seconds']['cpu'] for r in rows]);f=np.array([r['seconds']['fpga'] for r in rows])
        a.out.parent.mkdir(parents=True,exist_ok=True);onnx.save(graph,str(a.out.with_suffix('.onnx')))
        write_json(a.out,{'complete':True,'hardware_execution':True,'context_seconds':a.seconds,'runs':a.runs,
                         'cpu_threads':a.threads,'main_core':3,'spin_duration_us':spin,
                         'scope':'Complete warm block with transfers, masking and synchronization; no whole-model claim',
                         'input_shapes':{k:list(v.shape) for k,v in feed.items()},'first_physical_seconds':first,
                         'first_physical_counters':cold,'physical_oracle_bit_exact':True,
                         'cpu_p50':float(np.median(c)),'fpga_p50':float(np.median(f)),
                         'cpu_p95':float(np.percentile(c,95)),'fpga_p95':float(np.percentile(f,95)),
                         'mean_saving_95ci_seconds':list(np.percentile(np.random.default_rng(11102026).choice(c-f,(10000,len(c))).mean(axis=1),[2.5,97.5])),
                         'model_sha256':sha(model_path),'library_sha256':sha(library),'source_sha256':sha(__file__),
                         'graph_sha256':sha(a.out.with_suffix('.onnx')),'environment_before':env,
                         'environment_after':environment(),'paired_runs':rows})
        print('CPU',np.median(c),'FPGA',np.median(f),flush=True)
    finally:os.sched_setaffinity(0,original_affinity)


if __name__=='__main__':main()
