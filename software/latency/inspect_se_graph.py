"""Record original SE operator dependencies before attempting native fusion."""
import json
from pathlib import Path
import onnx
from onnx import helper,numpy_helper
ROOT=Path(__file__).resolve().parents[2]
model=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
initializers={v.name:numpy_helper.to_array(v) for v in model.graph.initializer}
nodes=[]
for node in model.graph.node:
    if '/encoder/encoder.1/mconv.23/' not in node.name:continue
    nodes.append({'name':node.name,'op':node.op_type,'domain':node.domain,
                  'inputs':list(node.input),'outputs':list(node.output),
                  'attributes':{a.name:helper.get_attribute_value(a) for a in node.attribute},
                  'constants':{i:{'shape':list(initializers[i].shape),'dtype':str(initializers[i].dtype)}
                               for i in node.input if i in initializers}})
path=ROOT/'reports/fused/se_graph_inspection.json'
path.write_text(json.dumps(nodes,indent=2,default=str)+'\n')
print(path.read_text())
