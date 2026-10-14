"""Check chain programs against the unchanged pair oracle before FPGA build."""
import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np
import onnx
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
sys.path.insert(0,str(ROOT/'software/ort_fpga_shortwide'))
sys.path.insert(0,str(ROOT/'software/ort_fpga_chain'))
from graph import candidate
from chain_graph import compile_chains
from boundary_lut import transform
from common import Frontend,read_audio,decode,sha,write_json
from latency20_boundary_screen import make_session

ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
model=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
pair,records=transform(candidate(model,True))
chain,groups=compile_chains(pair,True)
physical,pgroups=compile_chains(transform(candidate(model))[0])
boundary=ROOT/'software/latency/libboundary_lut.so'
old=ROOT/'software/ort_fpga_shortwide/libort_fpga.so'
new=ROOT/'software/ort_fpga_chain/libort_fpga.so'
runners={'pair':make_session(pair,[boundary,old]),'chain':make_session(chain,[boundary,new])}
front=Frontend(ROOT/'research/export/citrinet-256-ls')
vocab=(ROOT/'research/export/citrinet-256-ls/vocab.txt').read_text().splitlines()
audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')
rows=[]
for seconds in (.25,.5,1):
    x,n=front(audio[:round(seconds*16000)]);x=np.ascontiguousarray(x[:,:,:int(n[0])])
    feed={'features':x,'feature_lengths':n};start=time.perf_counter()
    before=runners['pair'].run(None,feed);after=runners['chain'].run(None,feed)
    for actual,expected in zip(after,before):np.testing.assert_array_equal(actual,expected)
    row={'seconds':seconds,'all_outputs_bit_exact':True,'text':decode(after[0][0],after[1][0],vocab),
         'check_seconds':time.perf_counter()-start}
    rows.append(row);print(json.dumps(row),flush=True)
a.out.parent.mkdir(parents=True,exist_ok=True)
onnx.save(physical,a.out.with_suffix('.onnx'))
write_json(a.out,{'complete':True,'hardware_execution':False,'all_outputs_bit_exact':True,
                 'groups':groups,'physical_groups':pgroups,'physical_transactions':len(groups),
                 'retained_boundaries':sum(g['retained_boundaries'] for g in groups),
                 'diagnostics':rows,'source_sha256':sha(__file__),'library_sha256':sha(new),
                 'graph_sha256':sha(a.out.with_suffix('.onnx')),
                 'compiler_sha256':sha(ROOT/'software/ort_fpga_chain/chain_graph.py'),
                 'representative_corpus_qualified':False})
