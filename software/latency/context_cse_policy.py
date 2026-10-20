"""Paired CPU/physical FPGA latency with exact duplicate graph calculations removed."""
import argparse,ctypes,json,random,sys,time,hashlib
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--spin-us',type=int,choices=(0,50,500,1000),default=1000)
    ap.add_argument('--model',type=Path,default=ROOT/'research/fused/cpu-int8-cse.onnx')
    ap.add_argument('--threads',type=int,choices=(1,2,4),default=4)
    ap.add_argument('--runtime',choices=('bulk','quad','screen'),default='bulk')
    ap.add_argument('--nodes',nargs='+',required=True)
    ap.add_argument('--wav',type=Path,default=ROOT/'research/eval/user-recording/speech.wav')
    ap.add_argument('--contexts',type=float,nargs='+',default=[.5,1,2,4,8,10])
    ap.add_argument('--runs',type=int,default=50)
    ap.add_argument('--warmups',type=int,default=3)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    if a.runs<20 or a.warmups<3:ap.error('At least 20 paired runs and three warmups required')
    runtime=ROOT/('software/ort_fpga_'+a.runtime)
    sys.path.insert(0,str(runtime))
    from probe import candidate,session,stats
    from common import Frontend,read_audio,decode,sha,identity,environment,write_json
    def policy_session(g,so=None,threads=4):
        opt=ort.SessionOptions();opt.intra_op_num_threads=threads;opt.inter_op_num_threads=1
        opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        opt.add_session_config_entry('session.intra_op.allow_spinning','1' if a.spin_us else '0')
        opt.add_session_config_entry('session.inter_op.allow_spinning','0')
        opt.add_session_config_entry('session.intra_op.spin_duration_us',str(a.spin_us))
        opt.add_session_config_entry('session.intra_op.spin_backoff_max','8')
        if so:opt.register_custom_ops_library(str(so.resolve()))
        return ort.InferenceSession(onnx.shape_inference.infer_shapes(g).SerializeToString(),opt,providers=['CPUExecutionProvider'])
    session=policy_session
    library=runtime/'libort_fpga.so'
    cpu_path=a.model
    directory=ROOT/'research/export/citrinet-256-ls'
    proof=json.loads(cpu_path.with_suffix('.json').read_text())
    assert sha(cpu_path)==proof['model_sha256'] and identity(directory)==proof['source_identity']
    validation_path=ROOT/'reports/fused/cse_arm_validation.json'
    validation=json.loads(validation_path.read_text())
    assert validation['complete'] and validation['all_logits_bit_exact']
    assert validation['cse_model_sha256']==sha(cpu_path)
    assert validation['transformation_source_sha256']==proof['transform_source_sha256']
    model=onnx.load(str(cpu_path));lib=ctypes.CDLL(str(library.resolve()))
    app='quad' if a.runtime=='quad' else 'bulk'
    clock=Path('/sys/bus/platform/devices/asr-v3-'+app+'-clock/set_rate')
    firmware=Path('/lib/firmware/xilinx/asr-v3-'+app+'/asr-v3-'+app+'.bit.bin')
    assert 99000000<=int(clock.read_text())<=101000000
    graph=candidate(model,a.nodes,quant=True)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    onnx.save(graph,str(a.out.with_suffix('.onnx')))
    setup={};runners={}
    for name,g,so in [('cpu',model,None),('fpga',graph,library),('oracle',candidate(model,a.nodes,True,True),library)]:
        start=time.perf_counter();runners[name]=session(g,so,threads=a.threads);setup[name]=time.perf_counter()-start
    frontend=Frontend(directory);vocab=(directory/'vocab.txt').read_text().splitlines()
    full=read_audio(a.wav);rng=random.Random(10102026);rows=[];summary=[]
    durations=sorted(set(a.contexts))
    if not durations or min(durations)<.02 or max(durations)>len(full)/16000+1e-9:
        raise ValueError('Contexts must fit source audio and support reflected STFT')
    def call(name,audio):
        # Let the previous session's bounded spin window expire outside timing.
        time.sleep(.003)
        before=stats(lib);start=time.perf_counter()
        x,n=frontend(audio);f=time.perf_counter()
        logits,length=runners[name].run(None,{'features':x,'feature_lengths':n});m=time.perf_counter()
        text=decode(logits[0],length[0],vocab);end=time.perf_counter()
        after=stats(lib);delta={k:after[k]-before[k] for k in after}
        assert np.all(np.isfinite(logits))
        if name=='cpu':assert not(delta['physical_calls'] or delta['oracle_calls'])
        if name=='fpga':assert delta['physical_calls']==len(a.nodes)
        return {'seconds':end-start,'frontend_seconds':f-start,'model_seconds':m-f,
                'decode_seconds':end-m,'text':text,'encoded_length':int(length[0]),
                'fpga_counters':delta},logits,length
    for seconds in durations:
        audio=np.ascontiguousarray(full[:round(seconds*16000)])
        oracle,expected,n=call('oracle',audio)
        cold,actual,an=call('fpga',audio)
        np.testing.assert_array_equal(expected,actual);np.testing.assert_array_equal(n,an)
        for _ in range(a.warmups):call('cpu',audio);call('fpga',audio)
        pairs=[];before_env=environment()
        for i in range(a.runs):
            order=['cpu','fpga'];rng.shuffle(order);pair={}
            for name in order:pair[name]=call(name,audio)[0]
            assert pair['cpu']['encoded_length']==pair['fpga']['encoded_length']
            pairs.append(pair);rows.append({'context_seconds':seconds,'repeat':i,'order':order,'results':pair})
        cpu=np.array([v['cpu']['seconds'] for v in pairs]);fg=np.array([v['fpga']['seconds'] for v in pairs])
        idx=np.random.default_rng(199026).integers(0,a.runs,(10000,a.runs))
        ci=np.percentile((cpu-fg)[idx].mean(axis=1),[2.5,97.5])
        c={'context_seconds':seconds,'cpu_p50':float(np.median(cpu)),'fpga_p50':float(np.median(fg)),
           'cpu_p95':float(np.percentile(cpu,95)),'fpga_p95':float(np.percentile(fg,95)),
           'mean_saving_95ci_seconds':ci.tolist(),'physical_oracle_bit_parity':True,
           'cpu_text':pairs[0]['cpu']['text'],'fpga_text':pairs[0]['fpga']['text'],
           'first_physical':cold,'environment_before':before_env,'environment_after':environment()}
        for name in ('cpu','fpga'):
            for phase in ('frontend','model','decode'):
                c[name+'_'+phase+'_p50']=float(np.median([v[name][phase+'_seconds'] for v in pairs]))
        summary.append(c)
        report={'hardware_execution':True,'microphone_capture_tested':False,
          'scope':'Resident waveform-in-memory frontend, graph and decoder latency; prefix outputs provisional',
          'runtime':a.runtime,'nodes':a.nodes,'contexts_requested':durations,
          'complete':len(summary)==len(durations),'runs':a.runs,'warmups':a.warmups,
          'cpu_threads':a.threads,'worker_spinning':bool(a.spin_us),'spin_duration_us':a.spin_us,'spin_backoff_max':8,'idle_between_calls_seconds':.003,'initialization_seconds':setup,
          'source_audio_sha256':sha(a.wav),'cpu_model_sha256':sha(cpu_path),
          'cpu_model_relative_path':str(cpu_path.relative_to(ROOT)),
          'numerical_validation_sha256':sha(validation_path),
          'fpga_graph_sha256':sha(a.out.with_suffix('.onnx')),'library_sha256':sha(library),
          'firmware_sha256':sha(firmware),'pl_clock_hz':int(clock.read_text()),
          'sources_sha256':{str(p.relative_to(ROOT)):sha(p) for p in
              [Path(__file__),runtime/'probe.py',runtime/'pointwise.cc',runtime/'qnc_transport.c']},
          'accuracy_against_full_transcript_claimed':False,'contexts':summary,'paired_runs':rows}
        write_json(a.out,report)
        print(seconds,'CPU',c['cpu_p50'],'FPGA',c['fpga_p50'],'saving CI',c['mean_saving_95ci_seconds'],flush=True)
if __name__=='__main__':main()
