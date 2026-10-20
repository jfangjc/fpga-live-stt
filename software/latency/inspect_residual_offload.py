"""Describe residual projections and their relation to retained FPGA blocks."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
sys.path.insert(0,str(ROOT/'software/ort_fpga_stream_registered'))
import onnx
from onnx import numpy_helper
from boundary_lut import transform
from pair_graph import candidate
from stream_graph import compile_chains
from common import write_json,sha
model=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
graph,groups=compile_chains(transform(candidate(model,False)[0])[0])
arrays={v.name:numpy_helper.to_array(v) for v in graph.graph.initializer}
nodes=list(graph.graph.node);producers={o:n for n in nodes for o in n.output}
chains=[n for n in nodes if n.op_type=='FpgaChain']
def lineage(name):
    result=[]
    for _ in range(8):
        node=producers.get(name)
        if node is None:break
        result.append({'name':node.name,'op':node.op_type,'inputs':list(node.input)})
        if node.op_type not in ('LookupMask','QuantizeLinear','DequantizeLinear','Where','Relu'):break
        name=node.input[2] if node.op_type=='Where' else node.input[0]
    return result
records=[]
for node in nodes:
    if node.op_type!='QLinearConv' or '/res.' not in node.name:continue
    prefix=node.name.split('/res.')[0]
    related=[c for c in chains if c.name.startswith(prefix+'/')]
    record={'name':node.name,'input':node.input[0],'output':node.output[0],
        'weights_shape':list(arrays[node.input[3]].shape),
        'attributes':{a.name:onnx.helper.get_attribute_value(a) for a in node.attribute},
        'input_lineage':lineage(node.input[0]),
        'chains':[{'name':c.name,'input':c.input[0],'same_input':c.input[0]==node.input[0],
                   'input_lineage':lineage(c.input[0])} for c in related]}
    records.append(record)
write_json(ROOT/'reports/fused/residual_offload_inspection.json',{'complete':True,'hardware_execution':False,
          'model_sha256':sha(ROOT/'research/fused/cpu-int8-cse.onnx'),'source_sha256':sha(__file__),'records':records})
for r in records:print(r['name'],r['weights_shape'],r['attributes'],'chains',[(c['name'],c['same_input']) for c in r['chains']],flush=True)
