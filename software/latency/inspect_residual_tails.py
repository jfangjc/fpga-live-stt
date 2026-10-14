"""Print original integer graph tails without executing model operations."""
import onnx
from pathlib import Path
from onnx import numpy_helper
ROOT=Path(__file__).resolve().parents[2]
g=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
p={o:n for n in g.graph.node for o in n.output}
arrays={v.name:numpy_helper.to_array(v) for v in g.graph.initializer}
def show(n,depth=0):
    print(' '*depth,n.name,n.op_type,list(n.input),list(n.output),flush=True)
    if depth<8:
        for i in n.input:
            if i in arrays:
                v=arrays[i];print(' '*(depth+1),'CONST',i,v.shape,v.dtype, v.item() if v.size==1 else '')
            elif i in p:show(p[i],depth+1)
for n in g.graph.node:
    if n.op_type=='Add' and 'encoder' in n.name:show(n)
