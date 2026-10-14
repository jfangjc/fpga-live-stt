"""Reuse Shape inputs with provably equal symbolic dimensions; no arithmetic edits."""
import argparse,copy,hashlib,json
from pathlib import Path
import numpy as np
import onnx
from onnx import helper,numpy_helper
ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def broadcast(a,b):
    if a is None or b is None:return None
    result=[]
    for x,y in zip((1,)*(max(len(a),len(b))-len(a))+a,(1,)*(max(len(a),len(b))-len(b))+b):
        if x==y:result.append(x)
        elif x==1:result.append(y)
        elif y==1:result.append(x)
        else:return None
    return tuple(result)
def ceildiv(x,n):
    if isinstance(x,int):return (x+n-1)//n
    if n==1:return x
    if isinstance(x,tuple) and x[0]=='ceil':return ('ceil',x[1],x[2]*n)
    return ('ceil',x,n)
def rewrite(model):
    result=copy.deepcopy(model);shapes={};values={};arrays={};canonical={};changes=[]
    def constant(name,array):
        array=np.asarray(array);arrays[name]=array;shapes[name]=tuple(array.shape)
        if array.size<=16:values[name]=array.tolist()
    for tensor in result.graph.initializer:constant(tensor.name,numpy_helper.to_array(tensor))
    for inp in result.graph.input:
        shapes[inp.name]=tuple(int(d.dim_value) if d.dim_value else ('symbol',d.dim_param or inp.name+'_'+str(i))
                               for i,d in enumerate(inp.type.tensor_type.shape.dim))
    unary={'Relu','Sigmoid','LogSoftmax','Identity','Cast','QuantizeLinear','DequantizeLinear','Not'}
    binary={'Add','Sub','Mul','Div','Less','GreaterOrEqual','Equal','And','Or'}
    for node in result.graph.node:
        attrs={a.name:helper.get_attribute_value(a) for a in node.attribute}
        ins=[shapes.get(n) for n in node.input];vs=[values.get(n) for n in node.input]
        shape=None;value=None;typ=node.op_type
        if typ=='Constant' and 'value' in attrs:
            constant(node.output[0],numpy_helper.to_array(attrs['value']));continue
        if typ in unary and ins:shape=ins[0]
        if typ in ('Identity','Cast') and vs:
            if typ=='Identity' or attrs.get('to') in (onnx.TensorProto.INT64,onnx.TensorProto.INT32):value=vs[0]
        if typ in binary and len(ins)>=2:shape=broadcast(ins[0],ins[1])
        if typ=='Where' and len(ins)==3:shape=broadcast(ins[0],broadcast(ins[1],ins[2]))
        if typ in ('Conv','QLinearConv'):
            wi=3 if typ=='QLinearConv' else 1;w=arrays.get(node.input[wi])
            if ins[0] is not None and len(ins[0])==3 and w is not None and w.ndim==3:
                stride=attrs.get('strides',[1])[0];dilation=attrs.get('dilations',[1])[0]
                pads=attrs.get('pads',[0,0]);auto=attrs.get('auto_pad',b'NOTSET')
                if (auto in (b'SAME_UPPER',b'SAME_LOWER') or
                    (auto in (b'NOTSET',b'') and sum(pads)==dilation*(w.shape[-1]-1))):
                    shape=(ins[0][0],int(w.shape[0]),ceildiv(ins[0][2],stride))
        if typ=='Shape' and ins[0] is not None:
            start=attrs.get('start',0);end=attrs.get('end',len(ins[0]))
            value=list(ins[0][start:end]);shape=(len(value),)
            key=(ins[0],start,end)
            if key in canonical:
                previous=canonical[key]
                if node.input[0]!=previous:
                    changes.append({'node':node.name,'original_input':node.input[0],
                                    'shared_input':previous,'symbolic_dimensions':ins[0],
                                    'slice_start':start,'slice_end':end})
                    node.input[0]=previous
            else:canonical[key]=node.input[0]
        if typ=='Gather' and ins[0] is not None and ins[1] is not None:
            axis=attrs.get('axis',0)%len(ins[0]);shape=ins[0][:axis]+ins[1]+ins[0][axis+1:]
            if isinstance(vs[0],list) and vs[1] is not None and axis==0:
                try:value=[vs[0][int(i)] for i in vs[1]] if isinstance(vs[1],list) else vs[0][int(vs[1])]
                except (IndexError,ValueError,TypeError):pass
        if typ=='Range' and vs[0]==0 and vs[2]==1 and vs[1] is not None:
            if isinstance(vs[1],(int,tuple)):shape=(vs[1],)
        if typ=='Unsqueeze' and ins[0] is not None:
            axes=vs[1] if len(vs)>1 else attrs.get('axes')
            if isinstance(axes,list) and all(isinstance(x,int) for x in axes):
                output_rank=len(ins[0])+len(axes);shape=list(ins[0])
                for axis in sorted(x%output_rank for x in axes):shape.insert(axis,1)
                shape=tuple(shape)
        if typ=='Transpose' and ins[0] is not None:
            perm=attrs.get('perm',list(reversed(range(len(ins[0])))));shape=tuple(ins[0][i] for i in perm)
        if typ=='ReduceSum' and ins[0] is not None:
            axes=vs[1] if len(vs)>1 else attrs.get('axes',list(range(len(ins[0]))))
            if isinstance(axes,list) and all(isinstance(x,int) for x in axes):
                axes={x%len(ins[0]) for x in axes}
                shape=tuple(1 if i in axes else x for i,x in enumerate(ins[0])) if attrs.get('keepdims',1) else tuple(x for i,x in enumerate(ins[0]) if i not in axes)
        if typ=='MatMul' and all(s is not None and len(s)>=2 for s in ins[:2]):
            if ins[0][-1]==ins[1][-2]:
                prefix=broadcast(ins[0][:-2],ins[1][:-2])
                if prefix is not None:shape=prefix+(ins[0][-2],ins[1][-1])
        if shape is not None:shapes[node.output[0]]=shape
        if value is not None:values[node.output[0]]=value
    onnx.checker.check_model(result)
    return result,changes

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,default=ROOT/'research/fused/cpu-int8.onnx')
    p.add_argument('--out',type=Path,default=ROOT/'research/fused/cpu-int8-shared-shapes.onnx')
    a=p.parse_args();original=onnx.load(str(a.model));result,changes=rewrite(original)
    if not changes:raise ValueError('No provable metadata sharing opportunities')
    a.out.parent.mkdir(parents=True,exist_ok=True);onnx.save(result,str(a.out))
    proof=json.loads(a.model.with_suffix('.json').read_text());assert proof['model_sha256']==sha(a.model)
    proof.update(model_sha256=sha(a.out),parent_model_sha256=sha(a.model),
                 transformation='Only Shape-node input aliases with equal proved symbolic dimensions',
                 transform_source_sha256=sha(__file__),metadata_input_changes=changes,
                 numerical_arithmetic_changed=False,physical_performance_validated=False)
    a.out.with_suffix('.json').write_text(json.dumps(proof,indent=2)+'\n')
    print('PASS:',len(changes),'Shape inputs shared; original arithmetic and weights preserved')
if __name__=='__main__':main()
