"""Larger-model CPU screening and paired physical bulk pointwise benchmarks.

The qualified 256-channel retained-block implementation is not modified.
The bulk experiment supports wider pointwise operators, with CPU DW/SE tails.
"""
import argparse, ctypes, gc, hashlib, json, sys, time
from pathlib import Path
import numpy as np
import onnx
from onnx import helper,numpy_helper
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/model-tools'))
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
sys.path.insert(0,str(ROOT/'software/fused'))
from citrinet_cpu import Frontend,read_audio,decode
from larger_tokenizer import load_decoder
from common import environment,errors,write_json,sha
from probe import candidate,stats

def make_session(model,threads,library=None):
    o=ort.SessionOptions();o.intra_op_num_threads=threads;o.inter_op_num_threads=1
    o.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL;o.log_severity_level=3
    o.add_session_config_entry('session.intra_op.allow_spinning','0')
    o.add_session_config_entry('session.inter_op.allow_spinning','0')
    if library:o.register_custom_ops_library(str(library))
    return ort.InferenceSession(str(model) if isinstance(model,Path) else model.SerializeToString(),o,providers=['CPUExecutionProvider'])

def main():
    p=argparse.ArgumentParser();p.add_argument('--model-dir',type=Path,required=True)
    p.add_argument('--model',type=Path);p.add_argument('--physical',action='store_true')
    p.add_argument('--runs',type=int,default=20);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--reuse-cpu-policies',action='store_true')
    a=p.parse_args();model=a.model or a.model_dir/'model.onnx'
    frontend=Frontend(a.model_dir);vocab,decode=load_decoder(a.model_dir)
    audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')
    contexts=[.5,1.,2.5];clips={c:audio[:int(c*16000)] for c in contexts}
    def call(s,x):
        start=time.perf_counter();features,lengths=frontend(x)
        logits,n=s.run(None,{'features':features,'feature_lengths':lengths})
        text=decode(logits[0],n[0],vocab)
        return time.perf_counter()-start,logits,n,text
    report={'model_sha256':sha(model),'model_dir':a.model_dir.as_posix(),'ort':ort.__version__,
            'hardware_execution':a.physical,'runs':a.runs,'contexts':[],
            'environment_before':environment(),'representative_accuracy_qualified':False,
            'timing_scope':'resident full audio frontend/model/decode; WAV IO and setup excluded; physical weights/transfers/synchronization included'}
    policies=[]
    if a.reuse_cpu_policies:
        prior=json.loads(a.out.read_text());assert prior['model_sha256']==sha(model)
        policies=prior['cpu_policies']
    for threads in (() if policies else (1,2,4)):
        s=make_session(model,threads);rows=[]
        for c,x in clips.items():
            for _ in range(3):call(s,x)
            values=[call(s,x)[0] for _ in range(a.runs)]
            rows.append({'context_seconds':c,'p50':float(np.median(values)),'p95':float(np.percentile(values,95)),'seconds':values})
        policies.append({'threads':threads,'contexts':rows});del s;gc.collect()
        print('CPU policy',threads,[(r['context_seconds'],round(r['p50']*1000,2)) for r in rows],flush=True)
    report['cpu_policies']=policies
    write_json(a.out,report)
    best={c:min(policies,key=lambda p:next(r['p50'] for r in p['contexts'] if r['context_seconds']==c))['threads'] for c in contexts}
    if a.physical:
        firmware=Path('/lib/firmware/xilinx/asr-v3-bulk/asr-v3-bulk.bit.bin')
        clock=int(Path('/sys/bus/platform/devices/asr-v3-bulk-clock/set_rate').read_text())
        assert abs(clock-100000000)<=5
        assert Path('/sys/module/qn_tile/parameters/bulk_protocol').read_text().strip()=='1'
        library=ROOT/'software/ort_fpga_bulk/libort_fpga.so';lib=ctypes.CDLL(str(library))
        g=onnx.load(model);arrays={v.name:numpy_helper.to_array(v) for v in g.graph.initializer};names=[]
        for n in g.graph.node:
            if n.op_type!='QLinearConv':continue
            attrs={x.name:helper.get_attribute_value(x) for x in n.attribute};w=arrays[n.input[3]]
            if w.ndim==3 and w.shape[2]==1 and max(w.shape[:2])<=1024 and attrs.get('group',1)==1 and attrs.get('strides',[1])==[1] and not any(attrs.get('pads',[0,0])):names.append(n.name)
        assert names
        physical=candidate(g,names,quant=True);oracle=candidate(g,names,oracle=True,quant=True)
        report.update({'offloaded_pointwise_count':len(names),'offloaded_nodes':names,'firmware_sha256':sha(firmware),'library_sha256':sha(library),'clock_hz':100000000,'clock_readback_hz':clock,'fused_256_path_compatible':False})
        for c,x in clips.items():
            cpu=make_session(model,best[c]);hw=make_session(physical,best[c],library);emulated=make_session(oracle,best[c],library)
            reference=call(emulated,x);actual=call(hw,x);standard=call(cpu,x)
            np.testing.assert_array_equal(actual[1],reference[1]);np.testing.assert_array_equal(actual[2],reference[2])
            row={'context_seconds':c,'threads':best[c],'physical_oracle_bit_exact':True,
                 'ort_cpu_same_text':standard[3]==actual[3],'cpu_text':standard[3],'fpga_text':actual[3],
                 'ort_cpu_max_logit_difference':float(np.max(np.abs(standard[1]-actual[1])))}
            del emulated;gc.collect()
            for _ in range(3):call(cpu,x);call(hw,x)
            times={'cpu':[],'fpga':[]};before=stats(lib)
            for i in range(a.runs):
                for kind in (('cpu','fpga') if i%2==0 else ('fpga','cpu')):
                    duration,logits,n,text=call(cpu if kind=='cpu' else hw,x);times[kind].append(duration)
                    if kind=='fpga':np.testing.assert_array_equal(logits,reference[1])
            after=stats(lib);row['counters']={k:after[k]-before[k] for k in after};assert row['counters']['physical_calls']==len(names)*a.runs
            for kind in times:
                row[kind+'_seconds']=times[kind];row[kind+'_p50']=float(np.median(times[kind]));row[kind+'_p95']=float(np.percentile(times[kind],95))
            row['speedup_factor']=row['cpu_p50']/row['fpga_p50'];report['contexts'].append(row)
            print('PHYSICAL',json.dumps({k:v for k,v in row.items() if k not in ('counters','cpu_seconds','fpga_seconds')}),flush=True)
            del hw,cpu;gc.collect();write_json(a.out,report)
    # Full-recording regression accuracy, never inferred from truncated-prefix transcripts.
    s=make_session(model,2);evaluation=[]
    for manifest in (ROOT/'research/eval/librispeech-mini/evaluation.jsonl',ROOT/'research/eval/user-recording/evaluation.jsonl'):
        for line in manifest.read_text().splitlines():
            r=json.loads(line);x=read_audio(manifest.parent/r['audio']);result=call(s,x)
            e,n=errors(r.get('reference',r.get('text')),result[3]);evaluation.append({'id':r['id'],'transcript':result[3],'errors':e,'reference_words':n,'audio_sha256':sha(manifest.parent/r['audio']),'reference_status':r.get('reference_status','regression reference')})
    report['evaluation']=evaluation;report['environment_after']=environment();report['complete']=True
    write_json(a.out,report);print('SAVED',a.out,flush=True)

if __name__=='__main__':main()
