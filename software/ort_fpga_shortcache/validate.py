"""Validate 32 retained pairs; hardware is explicitly limited to short windows."""
import argparse,ctypes,json,sys
from pathlib import Path
import numpy as np
import onnx
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
from probe import session,stats
from common import Frontend,identity,sha,corpus,read_audio,decode,errors,write_json
from graph import candidate

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--physical',action='store_true');ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();path=ROOT/'research/fused/cpu-int8-cse.onnx';model=onnx.load(path)
    proof=json.loads(path.with_suffix('.json').read_text());directory=ROOT/'research/export/citrinet-256-ls'
    assert sha(path)==proof['model_sha256'] and identity(directory)==proof['source_identity']
    library=Path(__file__).with_name('libort_fpga.so');lib=ctypes.CDLL(str(library.resolve()))
    graph=candidate(model);oracle=candidate(model,oracle=True)
    assert sum(n.op_type=='FpgaDepthwisePointwise' for n in graph.graph.node)==32
    runners={'cpu':session(model),'oracle':session(oracle,library)}
    if a.physical:runners['fpga']=session(graph,library)
    frontend=Frontend(directory);vocab=(directory/'vocab.txt').read_text().splitlines()
    records=[]
    for folder in ('user-recording','librispeech-mini','user-stress-ac'):
        records+=corpus(ROOT/'research/eval'/folder/'evaluation.jsonl',('evaluation','test'))
    rows=[];skipped=[];total={k:0 for k in runners};words=0
    for r in records:
        full=read_audio(r['path'])
        for seconds in [None,.25,.5,1,2]:
            if seconds and seconds>len(full)/16000:continue
            x,n=frontend(full if seconds is None else full[:round(seconds*16000)])
            x=np.ascontiguousarray(x[:,:,:int(n[0])])
            if a.physical and x.shape[2]>256:
                skipped.append({'id':r['id'],'context_seconds':seconds,'feature_times':x.shape[2],
                                'reason':'Physical short-cache input limit; no hardware execution or accuracy claim'})
                continue
            result={};deltas={};texts={}
            for name,runner in runners.items():
                before=stats(lib);result[name]=runner.run(None,{'features':x,'feature_lengths':n})
                deltas[name]={k:v-before[k] for k,v in stats(lib).items()}
                assert deltas[name]['physical_calls']==(32 if name=='fpga' else 0)
                assert deltas[name]['oracle_calls']==(32 if name=='oracle' else 0)
                np.testing.assert_array_equal(result[name][1],result['cpu'][1])
                texts[name]=decode(result[name][0][0],result[name][1][0],vocab)
            if a.physical:
                for p,q in zip(result['oracle'],result['fpga']):np.testing.assert_array_equal(p,q)
            text_exact=texts['cpu']==texts['oracle']
            if seconds is None:
                for name in runners:
                    err,count=errors(r.get('reference',r.get('text')),texts[name]);total[name]+=err
                words+=count
            rows.append({'id':r['id'],'context_seconds':seconds,'texts':texts,'length_exact':True,
                         'cpu_transcript_exact':text_exact,
                         'physical_oracle_bit_parity':True if a.physical else None,'counters':deltas})
        print('PASS',r['id'],flush=True)
    report={'complete':True,'hardware_execution':a.physical,'latency_acceptance':False,
            'model_sha256':sha(path),'library_sha256':sha(library),'source_sha256':sha(__file__),
            'graph_source_sha256':sha(Path(__file__).with_name('graph.py')),
            'accelerated_convolutions':64,'retained_pairs':32,'physical_max_feature_times':256,
            'clips':rows,'skipped':skipped,'errors':total,'words':words,'representative_corpus_qualified':False,
            'all_cpu_transcripts_exact':all(r['cpu_transcript_exact'] for r in rows),
            'all_prefix_transcripts_exact':all(r['cpu_transcript_exact'] for r in rows if r['context_seconds'] is not None),
            'diagnostic_wer_delta_percentage_points':100*(total['oracle']-total['cpu'])/words if words else None}
    graph_path=a.out.with_suffix('.onnx');onnx.save(graph,graph_path)
    report['fpga_graph_sha256']=sha(graph_path)
    report['selected_nodes']=[n.name for n in graph.graph.node if n.op_type=='FpgaDepthwisePointwise']
    selection=Path(__file__).with_name('selection.json')
    report['selection_sha256']=sha(selection) if selection.exists() else None
    if a.physical:
        report.update(firmware_sha256=sha(Path('/lib/firmware/xilinx/asr-v3-shortcache/asr-v3-shortcache.bit.bin')),
                      pl_clock_hz=int(Path('/sys/bus/platform/devices/asr-v3-shortcache-clock/set_rate').read_text()),
                      driver_sha256=sha(ROOT/'deployment/experimental-shortcache/qn_tile.ko'))
    write_json(a.out,report)
    print('PASS:',len(rows),'32-pair diagnostic cases;',len(skipped),'outside physical limit',flush=True)
    print(json.dumps({k:report[k] for k in ('all_cpu_transcripts_exact','all_prefix_transcripts_exact','errors','words','diagnostic_wer_delta_percentage_points')}),flush=True)
    assert all(r['cpu_transcript_exact'] for r in rows if r['context_seconds'] is not None),'Short-prefix transcript parity failed'
    if words:assert report['diagnostic_wer_delta_percentage_points']<=1,'Diagnostic WER budget exceeded'

if __name__=='__main__':main()
