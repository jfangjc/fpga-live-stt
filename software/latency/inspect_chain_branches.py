"""Inspect independent residual branches before choosing overlap experiments."""
import json,sys
from pathlib import Path
import onnx
ROOT=Path(__file__).resolve().parents[2]
for folder in ('software/fused','software/ort_fpga_bulk','software/ort_fpga_shortwide','software/ort_fpga_chain'):
    sys.path.insert(0,str(ROOT/folder))
from graph import candidate
from chain_graph import compile_chains
from boundary_lut import transform
model,groups=compile_chains(transform(candidate(onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')))[0])
nodes=list(model.graph.node);producer={out:n for n in nodes for out in n.output};rows=[]
for node in nodes:
    if node.op_type!='FpgaChain':continue
    block='/'.join(node.name.split('/')[:3]);res=[n for n in nodes if n.name.startswith(block+'/res.') and n.op_type=='QLinearConv']
    rows.append({'chain':node.name,'inputs':list(node.input),'outputs':list(node.output),
                 'input_producer':producer[node.input[0]].name if node.input[0] in producer else None,
                 'residuals':[{'name':n.name,'inputs':list(n.input),'outputs':list(n.output),
                               'input_producer':producer[n.input[0]].name if n.input[0] in producer else None,
                               'attributes':{a.name:onnx.helper.get_attribute_value(a) for a in n.attribute}} for n in res]})
out=ROOT/'reports/fused/chain_branch_analysis.json';out.write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))
