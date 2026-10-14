"""Paired warm in-memory frontend/model/decode CPU versus physical retained pair."""
import argparse,ctypes,json,os,random,sys,time
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
from probe import stats
from common import Frontend,read_audio,decode,sha,identity,environment,write_json
from graph import candidate


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--contexts',type=float,nargs='+',default=[.5,1])
    ap.add_argument('--runs',type=int,default=100)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();assert a.runs>=20
    cpu_path=ROOT/'research/fused/cpu-int8-cse.onnx';model=onnx.load(str(cpu_path))
    proof=json.loads(cpu_path.with_suffix('.json').read_text());directory=ROOT/'research/export/citrinet-256-ls'
    assert sha(cpu_path)==proof['model_sha256'] and identity(directory)==proof['source_identity']
    validation_path=ROOT/'reports/fused/shortwide_physical_validation.json'
    validation=json.loads(validation_path.read_text())
    library=Path(__file__).with_name('libort_fpga.so');lib=ctypes.CDLL(str(library.resolve()))
    assert validation['complete'] and validation['hardware_execution'] and validation['library_sha256']==sha(library)
    clock=Path('/sys/bus/platform/devices/asr-v3-shortwide-clock/set_rate')
    firmware=Path('/lib/firmware/xilinx/asr-v3-shortwide/asr-v3-shortwide.bit.bin')
    assert 99000000<=int(clock.read_text())<=101000000
    graph=candidate(model);oracle_graph=candidate(model,oracle=True)
    a.out.parent.mkdir(parents=True,exist_ok=True);onnx.save(graph,str(a.out.with_suffix('.onnx')))
    audio_path=ROOT/'research/eval/user-recording/speech.wav';audio=read_audio(audio_path)
    frontend=Frontend(directory);vocab=(directory/'vocab.txt').read_text().splitlines()
    before_affinity=os.sched_getaffinity(0);assert before_affinity=={0,1,2,3}
    os.sched_setaffinity(0,{3});rng=random.Random(11102026)
    rows=[];summaries=[];startup={}
    try:
        for seconds in a.contexts:
            assert .02<=seconds<=len(audio)/16000
            spin=10 if seconds>=1 else 0
            def session(g,physical):
                opt=ort.SessionOptions();opt.intra_op_num_threads=4;opt.inter_op_num_threads=1
                opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
                opt.add_session_config_entry('session.intra_op.allow_spinning','1' if spin else '0')
                opt.add_session_config_entry('session.inter_op.allow_spinning','0')
                opt.add_session_config_entry('session.intra_op.spin_duration_us',str(spin))
                opt.add_session_config_entry('session.intra_op.spin_backoff_max','8')
                opt.add_session_config_entry('session.intra_op_thread_affinities','1;2;3')
                if physical:opt.register_custom_ops_library(str(library.resolve()))
                return ort.InferenceSession(onnx.shape_inference.infer_shapes(g).SerializeToString(),opt,providers=['CPUExecutionProvider'])
            start=time.perf_counter()
            runners={'cpu':session(model,False),'fpga':session(graph,True),'oracle':session(oracle_graph,True)}
            startup[str(seconds)]={'session_seconds':time.perf_counter()-start}
            clip=np.ascontiguousarray(audio[:round(seconds*16000)])
            def call(kind):
                time.sleep(.003);before=stats(lib);start=time.perf_counter()
                x,n=frontend(clip);x=np.ascontiguousarray(x[:,:,:int(n[0])]);front=time.perf_counter()
                logits,length=runners[kind].run(None,{'features':x,'feature_lengths':n});model_end=time.perf_counter()
                text=decode(logits[0],length[0],vocab);end=time.perf_counter()
                delta={k:v-before[k] for k,v in stats(lib).items()}
                assert delta['physical_calls']==(32 if kind=='fpga' else 0) and delta['oracle_calls']==(32 if kind=='oracle' else 0)
                return {'seconds':end-start,'frontend_seconds':front-start,'model_seconds':model_end-front,
                        'decode_seconds':end-model_end,'text':text,'length':int(length[0]),'counters':delta},logits
            first,actual=call('fpga');emulated,expected=call('oracle');cpu,_=call('cpu')
            np.testing.assert_array_equal(actual,expected)
            assert first['text']==emulated['text']==cpu['text'] and first['length']==cpu['length']
            startup[str(seconds)]['first_physical_call']=first
            for _ in range(3):call('cpu');call('fpga')
            context_rows=[];env_before=environment()
            for i in range(a.runs):
                order=['cpu','fpga'];rng.shuffle(order);results={}
                for kind in order:results[kind],_=call(kind)
                assert results['cpu']['text']==results['fpga']['text']
                assert results['cpu']['length']==results['fpga']['length']
                assert results['fpga']['counters']['loads']==0 and results['fpga']['counters']['ioctls']==32
                row={'context_seconds':seconds,'index':i,'order':order,'results':results}
                rows.append(row);context_rows.append(row)
            c=np.array([r['results']['cpu']['seconds'] for r in context_rows]);f=np.array([r['results']['fpga']['seconds'] for r in context_rows])
            savings=c-f;bootstrap=np.random.default_rng(11102026).choice(savings,(10000,len(savings)),replace=True).mean(axis=1)
            summary={'context_seconds':seconds,'cpu_p50':float(np.median(c)),'fpga_p50':float(np.median(f)),
                     'cpu_p95':float(np.percentile(c,95)),'fpga_p95':float(np.percentile(f,95)),
                     'mean_saving_95ci_seconds':list(np.percentile(bootstrap,[2.5,97.5])),
                     'physical_oracle_bit_parity':True,'spin_duration_us':spin,
                     'environment_before':env_before,'environment_after':environment()}
            summaries.append(summary);print(json.dumps(summary),flush=True);del runners
    finally:os.sched_setaffinity(0,before_affinity)
    write_json(a.out,{'complete':True,'hardware_execution':True,'runtime':'shortcache','runs':a.runs,
                     'scope':'Paired warm resident audio; frontend, graph, decode and all warm transfers included',
                     'cpu_model_sha256':sha(cpu_path),'fpga_graph_sha256':sha(a.out.with_suffix('.onnx')),
                     'library_sha256':sha(library),'firmware_sha256':sha(firmware),'pl_clock_hz':int(clock.read_text()),
                     'driver_sha256':sha(ROOT/'deployment/experimental-shortwide/qn_tile.ko'),
                     'validation_sha256':sha(validation_path),'source_sha256':sha(__file__),
                     'graph_source_sha256':sha(Path(__file__).with_name('graph.py')),'audio_sha256':sha(audio_path),
                     'cpu_threads':4,'main_core':3,'worker_cores':[0,1,2],'feature_padding_policy':'trim_to_valid',
                     'startup':startup,'contexts':summaries,'paired_runs':rows,'representative_corpus_qualified':False,
                     'capture_tested':False})


if __name__=='__main__':main()
