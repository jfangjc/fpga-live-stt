"""Prove selected convolution accumulators fit INT32 for every UINT8 input."""
import json
from pathlib import Path
import numpy as np
import onnx
from chain_benchmark import ROOT,sha,write_json
proof=json.loads((ROOT/'reports/fused/stream_transport_oracle.json').read_text())
model=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx');nodes={n.name:n for n in model.graph.node}
arrays={v.name:onnx.numpy_helper.to_array(v) for v in model.graph.initializer};rows=[]
for names in proof['pairs']:
    for name in names:
        node=nodes[name];w=arrays[node.input[3]].astype(np.int64).reshape(arrays[node.input[3]].shape[0],-1)
        bias=arrays[node.input[8]].astype(np.int64) if len(node.input)==9 else np.zeros(w.shape[0],np.int64)
        ratio=(arrays[node.input[1]]*arrays[node.input[4]])/arrays[node.input[6]]
        constant=ratio<=np.float32(2**-32);w[constant]=0;bias[constant]=0
        zx=int(arrays[node.input[2]]);positive=np.maximum(w,0).sum(1);negative=np.minimum(w,0).sum(1)
        lo=bias-zx*positive+(255-zx)*negative;hi=bias+(255-zx)*positive-zx*negative
        assert np.all(lo>=-(1<<31)) and np.all(hi<(1<<31))
        correction=bias+(128-zx)*w.sum(1)
        assert np.all(correction>=-(1<<31)) and np.all(correction<(1<<31))
        rows.append({'name':name,'minimum_possible_biased_sum':int(lo.min()),'maximum_possible_biased_sum':int(hi.max()),
                     'constant_output_channels_normalized':np.flatnonzero(constant).tolist(),
                     'correction_fits_int32':True,'all_uint8_inputs_fit_int32':True})
write_json(ROOT/'reports/fused/stream_accumulator_bounds.json',{'complete':True,'hardware_execution':False,'convolutions':len(rows),
           'all_uint8_inputs_fit_int32':True,'rows':rows,'source_sha256':sha(__file__),
           'model_sha256':sha(ROOT/'research/fused/cpu-int8-cse.onnx'),'selection_proof_sha256':sha(ROOT/'reports/fused/stream_transport_oracle.json')})
print('PASS:',len(rows),'convolutions, every UINT8 input combination fits INT32')
