"""Inspect unoffloaded convolutions; no latency or correctness claim."""
import sys,json
from tail_benchmark import *
sys.path.insert(0,str(ROOT/'software/ort_fpga_stream_branch_transport'))
from branch_graph import compile_branches
from pair_graph import candidate
path=ROOT/'research/fused/cpu-int8-cse.onnx';model=onnx.load(path)
graph,records,bounds=compile_branches(transform(candidate(model,False)[0])[0])
graph,_=tails(graph)
values={v.name:v for v in graph.graph.initializer};rows=[]
for node in graph.graph.node:
    if node.op_type not in ('Conv','QLinearConv'):continue
    attrs={a.name:onnx.helper.get_attribute_value(a) for a in node.attribute}
    weight=node.input[3] if node.op_type=='QLinearConv' else node.input[1]
    shape=list(values[weight].dims) if weight in values else None
    rows.append({'name':node.name,'op':node.op_type,'weight_shape':shape,
                 'groups':attrs.get('group',1),'strides':attrs.get('strides',[1]),
                 'pads':attrs.get('pads',[0,0]),'dilations':attrs.get('dilations',[1])})
report={'complete':True,'hardware_execution':False,'latency_measured':False,
        'cpu_model_sha256':sha(path),'compiler_sha256':sha(ROOT/'software/ort_fpga_stream_branch_transport/branch_graph.py'),
        'source_sha256':sha(__file__),'remaining_convolutions':rows}
write_json(ROOT/'reports/fused/branch_cpu_remainder.json',report)
print(json.dumps(rows,indent=2))
