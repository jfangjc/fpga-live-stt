"""Inspect exact exported graph shapes and reject unsafe INT32 quantized biases."""
import argparse,json
from pathlib import Path
import numpy as np
import onnx
from onnx import numpy_helper,helper

def inspect(path):
    g=onnx.load(path);a={x.name:numpy_helper.to_array(x) for x in g.graph.initializer}
    conv=[];unsafe=[];unsafe_accumulator=[];max_bound=0
    for n in g.graph.node:
        if n.op_type not in ('Conv','QLinearConv'):continue
        w=a[n.input[3] if n.op_type=='QLinearConv' else n.input[1]]
        attrs={x.name:helper.get_attribute_value(x) for x in n.attribute}
        conv.append({'name':n.name,'shape':list(w.shape),'group':attrs.get('group',1)})
        if n.op_type=='QLinearConv' and len(n.input)>8:
            b=a[n.input[8]]
            if np.any(b==np.iinfo(np.int32).min):unsafe.append(n.name)
            if not np.all(np.isfinite(a[n.input[1]])) or not np.all(np.isfinite(a[n.input[4]])):unsafe.append(n.name+':nonfinite_scale')
            zx=int(a[n.input[2]]);sums=np.abs(w.astype(np.int64)).reshape(w.shape[0],-1).sum(1)
            bound=sums*max(zx,255-zx)+np.abs(b.astype(np.int64));max_bound=max(max_bound,int(bound.max()))
            if np.any(bound>np.iinfo(np.int32).max):unsafe_accumulator.append(n.name)
    return {'model':str(path),'initializer_elements':sum(v.size for v in a.values()),
            'convolution_count':len(conv),'convolutions':conv,'unsafe_quantized_bias_nodes':unsafe,
            'unsafe_int32_accumulator_nodes':unsafe_accumulator,'maximum_int32_accumulator_bound':max_bound,
            'fused_256_channel_path_compatible':all(c['shape'][0]==256 and c['shape'][1] in (1,256) for c in conv if c['group']==1 and c['shape'][-1]==1)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('models',nargs='+',type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    result=[inspect(m) for m in a.models];a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps([{k:v for k,v in r.items() if k!='convolutions'} for r in result],indent=2))
