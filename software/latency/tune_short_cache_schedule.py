"""Screen independent CPU/FPGA spin and IRQ policies; never claim acceptance."""
import argparse,ctypes,importlib.util,json,os,random,sys,time
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
from probe import stats
from common import Frontend,read_audio,decode,sha,write_json,identity,environment
from dma_irq import snapshot,configure
runtime=ROOT/'software/ort_fpga_shortcache'
spec=importlib.util.spec_from_file_location('_shortcache_schedule_graph',runtime/'graph.py')
graph_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(graph_module)

def session(graph,library,spin):
    opt=ort.SessionOptions();opt.intra_op_num_threads=4;opt.inter_op_num_threads=1
    opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
    for key,value in [('session.intra_op.allow_spinning','1' if spin else '0'),
                      ('session.inter_op.allow_spinning','0'),('session.intra_op.spin_duration_us',str(spin)),
                      ('session.intra_op.spin_backoff_max','8'),('session.intra_op_thread_affinities','1;2;3')]:
        opt.add_session_config_entry(key,value)
    if library:opt.register_custom_ops_library(str(library))
    return ort.InferenceSession(onnx.shape_inference.infer_shapes(graph).SerializeToString(),opt,providers=['CPUExecutionProvider'])

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runs',type=int,default=60);ap.add_argument('--cpu-runs',type=int,default=100)
    ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    assert a.runs>=30 and a.cpu_runs>=60
    model_path=ROOT/'research/fused/cpu-int8-cse.onnx';model=onnx.load(model_path)
    validation_path=ROOT/'reports/fused/shortcache_physical_validation.json'
    validation=json.loads(validation_path.read_text())
    library=runtime/'libort_fpga.so';lib=ctypes.CDLL(str(library.resolve()))
    assert validation['complete'] and validation['hardware_execution']
    assert validation['model_sha256']==sha(model_path) and validation['library_sha256']==sha(library)
    directory=ROOT/'research/export/citrinet-256-ls';metadata=json.loads(model_path.with_suffix('.json').read_text())
    assert identity(directory)==metadata['source_identity'] and sha(model_path)==metadata['model_sha256']
    firmware=Path('/lib/firmware/xilinx/asr-v3-shortcache/asr-v3-shortcache.bit.bin')
    driver=ROOT/'deployment/experimental-shortcache/qn_tile.ko'
    assert sha(firmware)==validation['firmware_sha256'] and sha(driver)==validation['driver_sha256']
    actual_clock=int(Path('/sys/bus/platform/devices/asr-v3-shortcache-clock/set_rate').read_text())
    assert 99000000<=actual_clock<=101000000
    physical=graph_module.candidate(model);oracle=graph_module.candidate(model,True)
    front=Frontend(directory);vocab=(directory/'vocab.txt').read_text().splitlines()
    audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')
    before_irq=snapshot();before_affinity=os.sched_getaffinity(0);assert before_affinity=={0,1,2,3}
    os.sched_setaffinity(0,{3});rng=random.Random(1110202601)
    cpu_screen=[];fpga_screen=[];selected=[]
    def save(complete):
        write_json(a.out,{'complete':complete,'hardware_execution':True,'timing_acceptance':False,
                        'scope':'Scheduling screen; fresh paired confirmation is required',
                        'cpu_screen':cpu_screen,'fpga_screen':fpga_screen,'selected':selected,
                        'cpu_model_sha256':sha(model_path),'library_sha256':sha(library),
                        'firmware_sha256':sha(firmware),'driver_sha256':sha(driver),'pl_clock_hz':actual_clock,
                        'validation_sha256':sha(validation_path),'selection_sha256':sha(runtime/'selection.json'),
                        'source_sha256':sha(__file__),'graph_source_sha256':sha(runtime/'graph.py'),
                        'cpu_threads':4,'fpga_threads':4,'main_core':3,'worker_cores':[0,1,2],
                        'irq_before':before_irq,'irq_after':snapshot(),'representative_corpus_qualified':False})
    try:
        for seconds in (.5,1):
            clip=np.ascontiguousarray(audio[:round(seconds*16000)])
            reference=None;reference_length=None;cpu_reference_text=None
            def call(runner,backend):
                time.sleep(.003);before=stats(lib);start=time.perf_counter()
                x,n=front(clip);x=np.ascontiguousarray(x[:,:,:int(n[0])]);front_end=time.perf_counter()
                logits,length=runner.run(None,{'features':x,'feature_lengths':n});model_end=time.perf_counter()
                text=decode(logits[0],length[0],vocab);end=time.perf_counter()
                delta={k:v-before[k] for k,v in stats(lib).items()}
                assert delta['physical_calls']==(32 if backend=='fpga' else 0)
                assert delta['oracle_calls']==(32 if backend=='oracle' else 0)
                return {'seconds':end-start,'frontend_seconds':front_end-start,'model_seconds':model_end-front_end,
                        'decode_seconds':end-model_end,'text':text,'length':int(length[0]),'counters':delta},logits
            spins=[0,10,100,1000];rng.shuffle(spins);candidates=[]
            for spin in spins:
                runner=session(model,None,spin);first,logits=call(runner,'cpu')
                if reference is None:reference=logits.copy();reference_length=first['length'];cpu_reference_text=first['text']
                else:np.testing.assert_array_equal(logits,reference)
                assert first['length']==reference_length and first['text']==cpu_reference_text
                for _ in range(4):call(runner,'cpu')
                rows=[];env_before=environment()
                for _ in range(a.cpu_runs):
                    row,_=call(runner,'cpu');assert row['text']==cpu_reference_text;rows.append(row)
                values=np.array([r['seconds'] for r in rows])
                result={'context_seconds':seconds,'spin_duration_us':spin,'runs':a.cpu_runs,
                        'p50':float(np.median(values)),'p95':float(np.percentile(values,95)),
                        'environment_before':env_before,'environment_after':environment(),'rows':rows}
                cpu_screen.append(result);candidates.append(result);del runner
                print('CPU_SCREEN',seconds,spin,result['p50'],result['p95'],flush=True);save(False)
            cpu_best=min(candidates,key=lambda r:r['p50']);cpu_spin=cpu_best['spin_duration_us']
            cpu_runner=session(model,None,cpu_spin)
            oracle_runner=session(oracle,library,0);expected_result,expected=call(oracle_runner,'oracle');del oracle_runner
            assert expected_result['text']==cpu_reference_text and expected_result['length']==reference_length
            choices=[(irq,spin) for irq in (0,3) for spin in (0,10,100,1000)];rng.shuffle(choices)
            fp_candidates=[]
            for irq,spin in choices:
                configure(irq);fpga_runner=session(physical,library,spin)
                first,actual=call(fpga_runner,'fpga');np.testing.assert_array_equal(actual,expected)
                assert first['text']==cpu_reference_text and first['length']==reference_length
                for _ in range(4):call(cpu_runner,'cpu');call(fpga_runner,'fpga')
                rows=[];env_before=environment()
                for i in range(a.runs):
                    order=['cpu','fpga'];rng.shuffle(order);values={}
                    for kind in order:
                        values[kind],_=call(cpu_runner if kind=='cpu' else fpga_runner,kind)
                    assert values['cpu']['text']==values['fpga']['text']==cpu_reference_text
                    assert values['cpu']['length']==values['fpga']['length']==reference_length
                    assert values['fpga']['counters']['loads']==0 and values['fpga']['counters']['ioctls']==32
                    rows.append({'index':i,'order':order,'results':values})
                c=np.array([r['results']['cpu']['seconds'] for r in rows]);f=np.array([r['results']['fpga']['seconds'] for r in rows])
                result={'context_seconds':seconds,'cpu_spin_duration_us':cpu_spin,'fpga_spin_duration_us':spin,
                        'dma_irq_core':irq,'runs':a.runs,'cpu_p50':float(np.median(c)),'fpga_p50':float(np.median(f)),
                        'cpu_p95':float(np.percentile(c,95)),'fpga_p95':float(np.percentile(f,95)),
                        'environment_before':env_before,'environment_after':environment(),'paired_runs':rows}
                fpga_screen.append(result);fp_candidates.append(result);del fpga_runner
                print('FPGA_SCREEN',seconds,'cpu_spin',cpu_spin,'irq',irq,'fpga_spin',spin,result['cpu_p50'],result['fpga_p50'],flush=True)
                save(False)
            best=min(fp_candidates,key=lambda r:r['fpga_p50'])
            selected.append({k:best[k] for k in ('context_seconds','cpu_spin_duration_us','fpga_spin_duration_us','dma_irq_core','cpu_p50','fpga_p50')})
            del cpu_runner
    finally:
        os.sched_setaffinity(0,before_affinity)
        for irq,value in before_irq.items():(Path('/proc/irq')/irq/'smp_affinity_list').write_text(value['requested'])
        after=snapshot();assert {i:v['requested'] for i,v in before_irq.items()}=={i:v['requested'] for i,v in after.items()}
    save(True);print('SCHEDULING_SCREEN_COMPLETE',json.dumps(selected),flush=True)

if __name__=='__main__':main()
