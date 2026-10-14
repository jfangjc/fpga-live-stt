"""Explain remaining pair guards without changing the graph or execution."""
import hashlib,json,sys,traceback
from pathlib import Path
import numpy as np
import onnx
from onnx import helper,numpy_helper

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_stream_branch512'))
from pair_graph import candidate,one_pair

path=ROOT/'research/fused/cpu-int8-cse.onnx'
model=onnx.load(path)
_,selected=candidate(model,False)
selected={pw for _,pw in selected}
producers={o:n for n in model.graph.node for o in n.output}
consumers={}
for node in model.graph.node:
    for name in node.input:consumers.setdefault(name,[]).append(node.name)
arrays={v.name:numpy_helper.to_array(v) for v in model.graph.initializer}
rows=[]
for pw in model.graph.node:
    if pw.op_type!='QLinearConv' or pw.name in selected:continue
    weight=arrays[pw.input[3]]
    if weight.shape!=(256,256,1):continue
    q=producers.get(pw.input[0])
    if q is None or q.op_type!='QuantizeLinear':continue
    where=producers.get(q.input[0])
    if where is None or where.op_type!='Where':continue
    dq=producers.get(where.input[2])
    if dq is None or dq.op_type!='DequantizeLinear':continue
    dw=producers.get(dq.input[0])
    if dw is None or dw.op_type!='QLinearConv':continue
    row={'dw':dw.name,'pw':pw.name,
         'dw_attributes':{a.name:helper.get_attribute_value(a) for a in dw.attribute},
         'intermediate_consumers':{n.output[0]:consumers[n.output[0]] for n in (dw,dq,where,q)}}
    row['boundary_parameters']=[]
    for name,left,right in (('dequant_vs_dw',dq.input[1:3],dw.input[6:8]),
                            ('quant_vs_pw',q.input[1:3],pw.input[1:3]),
                            ('quant_vs_dw',q.input[1:3],dw.input[6:8])):
        row['boundary_parameters'].append({'comparison':name,'left':list(left),'right':list(right),
            'same_names':list(left)==list(right),
            'same_values':all(a in arrays and b in arrays and arrays[a].dtype==arrays[b].dtype
                and arrays[a].shape==arrays[b].shape and np.array_equal(arrays[a],arrays[b])
                for a,b in zip(left,right))})
    try:
        one_pair(model,dw.name,pw.name,False)
        row['guard_passed']=True
    except AssertionError:
        frame=traceback.extract_tb(sys.exc_info()[2])[-1]
        row.update(guard_passed=False,failed_assertion_line=frame.lineno,failed_assertion=frame.line)
    rows.append(row)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
report={'complete':True,'hardware_execution':False,'latency_measured':False,
        'cpu_model_sha256':sha(path),'compiler_sha256':sha(ROOT/'software/ort_fpga_stream_branch512/pair_graph.py'),
        'source_sha256':sha(Path(__file__)),'pairs':rows}
out=ROOT/'reports/fused/remaining_pair_guards.json'
out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(rows,indent=2))
