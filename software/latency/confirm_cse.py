"""Randomized original/CSE CPU/FPGA quartet; includes frontend and decoder."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import random
import sys
import time
import numpy as np
import onnx
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
from probe import candidate,stats
from common import Frontend,read_audio,decode,sha,identity,environment,write_json

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--nodes',nargs='+',required=True)
    ap.add_argument('--contexts',type=float,nargs='+',default=[10])
    ap.add_argument('--threads',type=int,choices=(1,2,4),default=4)
    ap.add_argument('--spin-us',type=int,choices=(0,500,1000),default=1000)
    ap.add_argument('--main-core',type=int,choices=(0,3))
    ap.add_argument('--runs',type=int,default=100)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    if a.runs<50:ap.error('At least 50 randomized quartets required')
    model_paths={'original':ROOT/'research/fused/cpu-int8.onnx','cse':ROOT/'research/fused/cpu-int8-cse.onnx'}
    validation_path=ROOT/'reports/fused/cse_arm_validation.json'
    validation=json.loads(validation_path.read_text())
    physical_path=ROOT/'reports/fused/cse_physical_validation.json'
    physical=json.loads(physical_path.read_text())
    assert validation['complete'] and validation['all_logits_bit_exact']
    assert physical['complete'] and physical['hardware_execution'] and physical['wer_degradation_percentage_points']<=1
    assert all(r['physical_oracle_bit_parity'] for r in physical['clips'])
    assert sha(model_paths['cse'])==validation['cse_model_sha256']==physical['cpu_model_sha256']
    assert physical['nodes']==a.nodes
    directory=ROOT/'research/export/citrinet-256-ls';models={}
    for name,p in model_paths.items():
        proof=json.loads(p.with_suffix('.json').read_text())
        assert sha(p)==proof['model_sha256'] and identity(directory)==proof['source_identity']
        models[name]=onnx.load(str(p))
    library=ROOT/'software/ort_fpga_bulk/libort_fpga.so'
    firmware=Path('/lib/firmware/xilinx/asr-v3-bulk/asr-v3-bulk.bit.bin')
    clock=Path('/sys/bus/platform/devices/asr-v3-bulk-clock/set_rate')
    assert sha(library)==physical['library_sha256'] and sha(firmware)==physical['firmware_sha256']
    assert int(clock.read_text())==physical['pl_clock_hz']
    lib=ctypes.CDLL(str(library.resolve()))
    worker_cores=None
    if a.main_core is not None:
        assert sorted(os.sched_getaffinity(0))==[0,1,2,3]
        worker_cores=[v for v in range(4) if v!=a.main_core][:a.threads-1]
        os.sched_setaffinity(0,{a.main_core})
    def session(graph,hardware):
        opt=ort.SessionOptions();opt.intra_op_num_threads=a.threads;opt.inter_op_num_threads=1
        opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        opt.add_session_config_entry('session.intra_op.allow_spinning','1' if a.spin_us else '0')
        opt.add_session_config_entry('session.inter_op.allow_spinning','0')
        opt.add_session_config_entry('session.intra_op.spin_duration_us',str(a.spin_us))
        opt.add_session_config_entry('session.intra_op.spin_backoff_max','8')
        if worker_cores:opt.add_session_config_entry('session.intra_op_thread_affinities',';'.join(str(v+1) for v in worker_cores))
        if hardware:opt.register_custom_ops_library(str(library.resolve()))
        return ort.InferenceSession(onnx.shape_inference.infer_shapes(graph).SerializeToString(),opt,providers=['CPUExecutionProvider'])
    a.out.parent.mkdir(parents=True,exist_ok=True)
    graphs={'original_cpu':models['original'],'original_fpga':candidate(models['original'],a.nodes,quant=True),
            'cpu':models['cse'],'fpga':candidate(models['cse'],a.nodes,quant=True)}
    onnx.save(graphs['fpga'],str(a.out.with_suffix('.onnx')))
    runners={};setup={}
    for name,graph in graphs.items():
        start=time.perf_counter();runners[name]=session(graph,name.endswith('fpga'));setup[name]=time.perf_counter()-start
    start=time.perf_counter()
    oracle_runner=session(candidate(models['cse'],a.nodes,oracle=True,quant=True),True)
    setup['oracle_validation']=time.perf_counter()-start
    frontend=Frontend(directory);vocab=(directory/'vocab.txt').read_text().splitlines()
    wav=ROOT/'research/eval/user-recording/speech.wav';full=read_audio(wav)
    if not a.contexts or min(a.contexts)<.02 or max(a.contexts)>len(full)/16000:
        raise ValueError('Invalid context')
    def call(name,audio):
        time.sleep(.003)
        before=stats(lib);start=time.perf_counter()
        x,n=frontend(audio);f=time.perf_counter()
        y,enc=runners[name].run(None,{'features':x,'feature_lengths':n});m=time.perf_counter()
        text=decode(y[0],enc[0],vocab);end=time.perf_counter()
        delta={k:v-before[k] for k,v in stats(lib).items()}
        assert delta['physical_calls']==(len(a.nodes) if name.endswith('fpga') else 0)
        assert delta['oracle_calls']==0 and np.all(np.isfinite(y))
        return {'seconds':end-start,'frontend_seconds':f-start,'model_seconds':m-f,'decode_seconds':end-m,
                'text':text,'encoded_length':int(enc[0]),'fpga_counters':delta},y,enc
    rng=random.Random(101026);rows=[];contexts=[]
    for seconds in sorted(set(a.contexts)):
        audio=np.ascontiguousarray(full[:round(seconds*16000)])
        first={name:call(name,audio) for name in runners}
        for old,new in [('original_cpu','cpu'),('original_fpga','fpga')]:
            np.testing.assert_array_equal(first[old][1],first[new][1]);np.testing.assert_array_equal(first[old][2],first[new][2])
        time.sleep(.003)
        x,n=frontend(audio);before=stats(lib)
        expected,expected_length=oracle_runner.run(None,{'features':x,'feature_lengths':n})
        after=stats(lib)
        assert after['oracle_calls']-before['oracle_calls']==len(a.nodes)
        assert after['physical_calls']==before['physical_calls']
        np.testing.assert_array_equal(expected,first['fpga'][1])
        np.testing.assert_array_equal(expected_length,first['fpga'][2])
        for _ in range(3):
            for name in runners:call(name,audio)
        pairs=[];before_env=environment()
        for i in range(a.runs):
            order=list(runners);rng.shuffle(order);pair={name:call(name,audio)[0] for name in order}
            assert pair['original_cpu']['text']==pair['cpu']['text']
            assert pair['original_fpga']['text']==pair['fpga']['text']
            pairs.append(pair);rows.append({'context_seconds':seconds,'repeat':i,'order':order,'results':pair})
        durations={name:np.array([v[name]['seconds'] for v in pairs]) for name in runners}
        indices=np.random.default_rng(101026).integers(0,a.runs,(10000,a.runs))
        def ci(old,new):return np.percentile((durations[old]-durations[new])[indices].mean(1),[2.5,97.5]).tolist()
        c={'context_seconds':seconds,'physical_oracle_bit_parity':True,'old_new_cpu_bit_parity':True,'old_new_fpga_bit_parity':True,
           'environment_before':before_env,'environment_after':environment(),
           'mean_saving_95ci_seconds':ci('cpu','fpga'),
           'cse_cpu_optimization_saving_95ci_seconds':ci('original_cpu','cpu'),
           'cse_fpga_optimization_saving_95ci_seconds':ci('original_fpga','fpga')}
        for name,data in durations.items():
            c[name+'_p50']=float(np.median(data));c[name+'_p95']=float(np.percentile(data,95))
            c[name+'_text']=pairs[0][name]['text']
        contexts.append(c)
        report={'complete':len(contexts)==len(set(a.contexts)),'hardware_execution':True,
          'scope':'Randomized quartet of original/CSE CPU/physical FPGA; resident in-memory frontend, graph and decoder',
          'runtime':'bulk','nodes':a.nodes,'runs':a.runs,'warmups':3,'cpu_threads':a.threads,
          'spin_duration_us':a.spin_us,'worker_spinning':bool(a.spin_us),'spin_backoff_max':8,
          'main_core':a.main_core,'worker_cores':worker_cores,'idle_between_calls_seconds':.003,
          'initialization_seconds':setup,'cpu_model_relative_path':'research/fused/cpu-int8-cse.onnx',
          'cpu_model_sha256':sha(model_paths['cse']),'original_cpu_model_sha256':sha(model_paths['original']),
          'fpga_graph_sha256':sha(a.out.with_suffix('.onnx')),'library_sha256':sha(library),'firmware_sha256':sha(firmware),
          'pl_clock_hz':int(clock.read_text()),'numerical_validation_sha256':sha(validation_path),
          'physical_validation_sha256':sha(physical_path),'source_audio_sha256':sha(wav),
          'sources_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),ROOT/'software/latency/eliminate_duplicates.py',ROOT/'software/latency/share_shape_metadata.py',ROOT/'software/ort_fpga_bulk/probe.py']},
          'microphone_capture_tested':False,'accuracy_against_full_transcript_claimed':False,'contexts':contexts,'paired_runs':rows}
        write_json(a.out,report)
        print(seconds,{k:round(c[k+'_p50']*1000,3) for k in runners},'FPGA saving CI',c['mean_saving_95ci_seconds'],flush=True)

if __name__=='__main__':main()
