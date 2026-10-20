"""Gate additional block arithmetic before streamed hardware development."""
import argparse,json,sys,os
from pathlib import Path
import numpy as np
import onnx
from tail_benchmark import *
sys.path.insert(0,str(ROOT/'software/ort_fpga_stream_exact'))
from pair_graph import candidate as all_pairs
from stream_graph import compile_chains as all_chains
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
path=ROOT/'research/fused/cpu-int8-cse.onnx';original=onnx.load(path)
pair,pairs=all_pairs(original,True);graph,groups=all_chains(transform(pair)[0],True);graph,tail_records=tails(graph)
library=ROOT/'software/ort_fpga_stream_exact/libort_fpga.so';boundary=ROOT/'software/latency/libboundary_lut.so'
config={'threads':4,'spin':10,'level':'extended'}
affinity=os.sched_getaffinity(0);rows=[]
try:
    os.sched_setaffinity(0,{3})
    oracle=make_session(graph,config,[boundary,library]);cpu=make_session(original,config)
    frontend=Frontend(ROOT/'research/export/citrinet-256-ls');vocab=(ROOT/'research/export/citrinet-256-ls/vocab.txt').read_text().splitlines()
    records=[]
    for folder in ('user-recording','librispeech-mini','user-stress-ac'):records+=corpus(ROOT/'research/eval'/folder/'evaluation.jsonl',('evaluation','test'))
    for record in records:
        audio=read_audio(record['path'])
        for seconds in (.25,.5,1,2):
            x,n=frontend(np.ascontiguousarray(audio[:round(seconds*16000)]));x=np.ascontiguousarray(x[:,:,:int(n[0])]);feed={'features':x,'feature_lengths':n}
            actual,length=oracle.run(None,feed);reference,ref_length=cpu.run(None,feed)
            np.testing.assert_array_equal(length,ref_length)
            text=decode(actual[0],length[0],vocab);ref=decode(reference[0],ref_length[0],vocab)
            row={'id':record['id'],'seconds':seconds,'text':text,'cpu_text':ref,'text_exact':text==ref,'length_exact':True,
                 'all_cpu_logits_bit_exact':bool(np.array_equal(actual,reference)),
                 'maximum_logit_difference':float(np.max(np.abs(actual-reference)))}
            rows.append(row);print(json.dumps(row),flush=True)
finally:os.sched_setaffinity(0,affinity)
onnx.save(graph,a.out.with_suffix('.onnx'))
write_json(a.out,{'complete':True,'hardware_execution':False,'physical_backend_implemented':False,'pairs':pairs,'groups':groups,
                 'retained_pairs':len(pairs),'transactions':len(groups),'all_diagnostic_transcripts_equal':all(r['text_exact'] for r in rows),'all_cpu_logits_bit_exact':all(r['all_cpu_logits_bit_exact'] for r in rows),
                 'representative_wer_qualified':False,'clips':rows,'library_sha256':sha(library),'cpu_model_sha256':sha(path),
                 'source_sha256':sha(__file__),'runtime_source_sha256':sha(ROOT/'software/ort_fpga_stream_exact/pointwise.cc'),
                 'pair_compiler_sha256':sha(ROOT/'software/ort_fpga_stream_exact/pair_graph.py'),'chain_compiler_sha256':sha(ROOT/'software/ort_fpga_stream_exact/stream_graph.py'),
                 'boundary_transform_sha256':sha(ROOT/'software/latency/boundary_lut.py'),'tail_transform_sha256':sha(ROOT/'software/latency/residual_tail.py'),
                 'graph_sha256':sha(a.out.with_suffix('.onnx'))})
print('Completed software arithmetic gate:',len(pairs),'pairs',len(groups),'blocks; transcript matches',sum(r['text_exact'] for r in rows),'/',len(rows))
