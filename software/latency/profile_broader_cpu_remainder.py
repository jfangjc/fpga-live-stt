"""Profile CPU nodes in the broader oracle graph while hardware builds.

Oracle convolution time is excluded. CPU attribution is diagnostic and can be
affected by profiling and oracle execution; it is not hybrid latency evidence.
"""
import argparse,ctypes,json,os,sys
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
sys.path.insert(0,str(ROOT/'software/ort_fpga_shortwide'))
sys.path.insert(0,str(ROOT/'software/ort_fpga_stream_branch512'))
from common import Frontend,read_audio,sha,write_json,environment
from pair_graph import candidate
from branch_graph import compile_branches
from boundary_lut import transform
from split_scale_pairs import expand
from retain_stride_pointwise import retain
from residual_tail import transform as tails
from se_pool import transform as pool
from probe import stats
from check_more_model_evidence import verify

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--runs',type=int,default=10);a=ap.parse_args();assert a.runs>=5
    verify()
    model_path=ROOT/'research/fused/cpu-int8-cse.onnx'
    original=onnx.load(model_path);expanded,_=expand(original)
    graph,_,_=compile_branches(retain(transform(candidate(expanded,True)[0])[0],True)[0],True)
    graph,_=tails(graph);pooled,_=pool(graph)
    library=ROOT/'software/ort_fpga_stream_branch512/libort_fpga.so'
    lib=ctypes.CDLL(str(library));front=Frontend(ROOT/'research/export/citrinet-256-ls')
    audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')
    cpu_options=ort.SessionOptions();cpu_options.intra_op_num_threads=4
    reference=ort.InferenceSession(original.SerializeToString(),cpu_options,providers=['CPUExecutionProvider'])
    affinity=os.sched_getaffinity(0);contexts=[];a.out.parent.mkdir(parents=True,exist_ok=True)
    try:
        os.sched_setaffinity(0,{3})
        for seconds in (.5,1,2.5):
            x,n=front(np.ascontiguousarray(audio[:round(seconds*16000)]))
            feed={'features':np.ascontiguousarray(x[:,:,:int(n[0])]),'feature_lengths':n}
            expected=reference.run(None,feed)
            for kind,model in (('tail',graph),('pool',pooled)):
                opt=ort.SessionOptions();opt.intra_op_num_threads=4;opt.inter_op_num_threads=1
                opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
                opt.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
                opt.add_session_config_entry('session.intra_op_thread_affinities','1;2;3')
                opt.add_session_config_entry('session.intra_op.allow_spinning','1')
                opt.add_session_config_entry('session.intra_op.spin_duration_us','10')
                opt.add_session_config_entry('session.inter_op.allow_spinning','0')
                opt.log_severity_level=3;opt.enable_profiling=True
                opt.profile_file_prefix=str(a.out.with_suffix(''))+f'_{seconds}_{kind}'
                for path in (library,ROOT/'software/latency/libboundary_lut.so',ROOT/'software/latency/libresidual_tail.so',ROOT/'software/latency/libse_pool.so'):
                    opt.register_custom_ops_library(str(path))
                runner=ort.InferenceSession(model.SerializeToString(),opt,providers=['CPUExecutionProvider'])
                before=stats(lib)
                for _ in range(5+a.runs):
                    actual=runner.run(None,feed)
                    for left,right in zip(expected,actual):np.testing.assert_array_equal(left,right)
                after=stats(lib)
                assert after['physical_calls']==before['physical_calls']==0
                assert after['oracle_calls']-before['oracle_calls']==128*(5+a.runs)
                path=Path(runner.end_profiling());events=json.loads(path.read_text());collected={}
                for event in events:
                    name=event.get('name','');args=event.get('args',{})
                    if event.get('cat')!='Node' or not name.endswith('_kernel_time'):continue
                    op=args.get('op_name','')
                    if op.startswith('Oracle') or op.startswith('Fpga'):continue
                    key=(name[:-len('_kernel_time')],op)
                    collected.setdefault(key,[]).append(float(event['dur']))
                rows=[{'name':name,'op':op,'median_us':float(np.median(values[5:])),
                       'samples':len(values)-5} for (name,op),values in collected.items()]
                assert rows and all(r['samples']==a.runs for r in rows)
                rows.sort(key=lambda r:r['median_us'],reverse=True)
                contexts.append({'seconds':seconds,'graph':kind,'all_logits_bit_exact':True,
                                 'profile_path':str(path),'profile_sha256':sha(path),'cpu_nodes':rows})
                print(json.dumps({'seconds':seconds,'graph':kind,'top_cpu_nodes':rows[:12]}),flush=True)
                del runner
    finally:os.sched_setaffinity(0,affinity)
    sources=[Path(__file__),model_path,library,ROOT/'software/latency/libboundary_lut.so',
             ROOT/'software/latency/libresidual_tail.so',ROOT/'software/latency/libse_pool.so',
             ROOT/'software/latency/retain_stride_pointwise.py',ROOT/'software/latency/split_scale_pairs.py',
             ROOT/'software/ort_fpga_stream_branch512/branch_graph.py']
    write_json(a.out,{'complete':True,'hardware_execution':False,'timing_acceptance':False,
                     'profiling_only':True,'runs_per_context_graph':a.runs,'contexts':contexts,
                     'environment':environment(),'sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in sources},
                     'note':'CPU event attribution in an exact oracle graph; not a physical latency result or speedup prediction'})

if __name__=='__main__':main()
