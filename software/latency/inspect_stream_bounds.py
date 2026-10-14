import json
import numpy as np
import onnx
from chain_benchmark import ROOT
proof=json.loads((ROOT/'reports/fused/stream_transport_oracle.json').read_text())
g=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx');nodes={n.name:n for n in g.graph.node};a={v.name:onnx.numpy_helper.to_array(v) for v in g.graph.initializer}
unsafe=live=0
for pair in proof['pairs']:
    for name in pair:
        n=nodes[name];w=a[n.input[3]].astype(np.int64).reshape(256,-1);b=a[n.input[8]].astype(np.int64) if len(n.input)==9 else np.zeros(256,np.int64)
        z=int(a[n.input[2]]);pos=np.maximum(w,0).sum(1);neg=np.minimum(w,0).sum(1)
        lo=b-z*pos+(255-z)*neg;hi=b+(255-z)*pos-z*neg
        mask=(lo<-(1<<31))|(hi>=(1<<31));ratio=(a[n.input[1]]*a[n.input[4]])/a[n.input[6]]
        unsafe+=int(mask.sum());live+=int((mask&(ratio>np.float32(2**-32))).sum())
print(json.dumps({'unsafe_bias_channels':unsafe,'unsafe_live_scale_channels':live}))
