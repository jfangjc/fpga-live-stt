"""Confirm builtin residual arithmetic matches the unmodified chain oracle."""
import argparse,gc,json,os
from pathlib import Path
import numpy as np
import onnx
from chain_benchmark import ROOT,make_session,read_audio,Frontend,sha,write_json
from graph import candidate
from chain_graph import compile_chains
from boundary_lut import transform
import sys
sys.path.insert(0,str(ROOT/'software/ort_fpga_pipeline'))
from pipeline_graph import fuse_residuals
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
model=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
original,groups=compile_chains(transform(candidate(model,True))[0],True);overlap,records=fuse_residuals(original)
boundary=ROOT/'software/latency/libboundary_lut.so';parent=ROOT/'software/ort_fpga_chain/libort_fpga.so'
library=ROOT/'software/ort_fpga_pipeline/libort_fpga.so';config={'threads':4,'spin':10,'level':'extended'}
affinity=os.sched_getaffinity(0);rows=[]
try:
    os.sched_setaffinity(0,{3});old=make_session(original,config,[boundary,parent]);new=make_session(overlap,config,[boundary,library])
    front=Frontend(ROOT/'research/export/citrinet-256-ls');audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')
    for seconds in (.25,.5,1,2.5):
        x,n=front(np.ascontiguousarray(audio[:round(seconds*16000)]));x=np.ascontiguousarray(x[:,:,:int(n[0])]);feed={'features':x,'feature_lengths':n}
        expected=old.run(None,feed);actual=new.run(None,feed)
        for left,right in zip(actual,expected):np.testing.assert_array_equal(left,right)
        row={'seconds':seconds,'all_outputs_bit_exact':True};rows.append(row);print(json.dumps(row),flush=True)
finally:os.sched_setaffinity(0,affinity)
onnx.save(overlap,a.out.with_suffix('.onnx'))
write_json(a.out,{'complete':True,'hardware_execution':False,'all_outputs_bit_exact':True,'records':records,'clips':rows,
                  'library_sha256':sha(library),'parent_library_sha256':sha(parent),'compiler_sha256':sha(ROOT/'software/ort_fpga_pipeline/pipeline_graph.py'),
                  'runtime_source_sha256':sha(ROOT/'software/ort_fpga_pipeline/pointwise.cc'),
                  'transport_source_sha256':sha(ROOT/'software/ort_fpga_pipeline/qnc_transport.c'),
                  'source_sha256':sha(__file__),'graph_sha256':sha(a.out.with_suffix('.onnx'))})
