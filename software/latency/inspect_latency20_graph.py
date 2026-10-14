import json
from pathlib import Path
import sys
import onnx
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_shortwide'))
from graph import candidate
from boundary_lut import transform
model=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
graph,records=transform(candidate(model))
producers={o:n for n in graph.graph.node for o in n.output}
rows=[]
for n in graph.graph.node:
    if n.op_type!='FpgaDepthwisePointwise':continue
    chain=[];cursor=n.input[0]
    for _ in range(5):
        if cursor not in producers:break
        p=producers[cursor]
        chain.append({'name':p.name,'op':p.op_type,'inputs':list(p.input)})
        cursor=p.input[0]
    rows.append({'name':n.name,'input_chain':chain,'mask':n.input[-1]})
(ROOT/'reports/fused/latency20_boundary_topology.json').write_text(json.dumps({'pairs':rows,'boundaries':records},indent=2)+'\n')
print(json.dumps(rows[:8],indent=2))
