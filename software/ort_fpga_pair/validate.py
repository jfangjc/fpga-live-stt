"""Check native fused-pair oracle, optionally physical FPGA, on full/prefix diagnostics."""
import argparse,ctypes,json,sys
from pathlib import Path
import numpy as np
import onnx
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
from probe import session,stats
from common import Frontend,read_audio,decode,corpus,errors,sha,identity,write_json
from graph import candidate


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--physical',action='store_true')
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    path=ROOT/'research/fused/cpu-int8-cse.onnx';model=onnx.load(str(path))
    proof=json.loads(path.with_suffix('.json').read_text());directory=ROOT/'research/export/citrinet-256-ls'
    assert sha(path)==proof['model_sha256'] and identity(directory)==proof['source_identity']
    library=Path(__file__).with_name('libort_fpga.so');lib=ctypes.CDLL(str(library.resolve()))
    runners={'cpu':session(model),'oracle':session(candidate(model,oracle=True),library)}
    if a.physical:runners['fpga']=session(candidate(model),library)
    frontend=Frontend(directory);vocab=(directory/'vocab.txt').read_text().splitlines()
    records=[]
    for folder in ('user-recording','librispeech-mini','user-stress-ac'):
        records += corpus(ROOT/'research/eval'/folder/'evaluation.jsonl',('evaluation','test'))
    rows=[];total={k:0 for k in runners};words=0
    for r in records:
        full=read_audio(r['path'])
        for seconds in [None,.25,.5,1]:
            if seconds and seconds>len(full)/16000:continue
            x,n=frontend(full if seconds is None else full[:round(seconds*16000)])
            x=np.ascontiguousarray(x[:,:,:int(n[0])]);feed={'features':x,'feature_lengths':n}
            result={};deltas={};texts={}
            for name,runner in runners.items():
                before=stats(lib);result[name]=runner.run(None,feed)
                deltas[name]={k:v-before[k] for k,v in stats(lib).items()}
                assert deltas[name]['physical_calls']==(1 if name=='fpga' else 0)
                assert deltas[name]['oracle_calls']==(1 if name=='oracle' else 0)
                np.testing.assert_array_equal(result[name][1],result['cpu'][1])
                texts[name]=decode(result[name][0][0],result[name][1][0],vocab)
            if a.physical:
                for p,q in zip(result['oracle'],result['fpga']):np.testing.assert_array_equal(p,q)
            assert texts['cpu']==texts['oracle']
            if seconds is None:
                for name in runners:
                    err,count=errors(r.get('reference',r.get('text')),texts[name]);total[name]+=err
                words+=count
            rows.append({'id':r['id'],'context_seconds':seconds,'texts':texts,'length_exact':True,
                         'physical_oracle_bit_parity':True if a.physical else None,'counters':deltas})
        print('PASS',r['id'],flush=True)
    report={'complete':True,'hardware_execution':a.physical,'latency_acceptance':False,
                     'model_sha256':sha(path),'library_sha256':sha(library),'source_sha256':sha(__file__),
                     'graph_source_sha256':sha(Path(__file__).with_name('graph.py')),
                     'clips':rows,'errors':total,'words':words,'representative_corpus_qualified':False}
    if a.physical:
        graph_path=a.out.with_suffix('.onnx');onnx.save(candidate(model),str(graph_path))
        report.update(firmware_sha256=sha(Path('/lib/firmware/xilinx/asr-v3-pair/asr-v3-pair.bit.bin')),
                      pl_clock_hz=int(Path('/sys/bus/platform/devices/asr-v3-pair-clock/set_rate').read_text()),
                      driver_sha256=sha(ROOT/'deployment/experimental-pair/qn_tile.ko'),
                      fpga_graph_sha256=sha(graph_path))
    write_json(a.out,report)


if __name__=='__main__':main()
