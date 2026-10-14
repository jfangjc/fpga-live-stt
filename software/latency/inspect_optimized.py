"""Inspect ARM ORT graph transformations; not a performance benchmark."""
import sys,json,collections,argparse
from pathlib import Path
import onnx
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
from probe import candidate
from common import sha,write_json
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--out',type=Path,required=True);a=p.parse_args()
m=onnx.load(str(ROOT/'research/fused/cpu-int8.onnx'));rows={}
for name,nodes in [('cpu',[]),('one',['/encoder/encoder.1/mconv.16/conv/Conv_quant']),
                   ('six',['/encoder/encoder.1/mconv.1/conv/Conv_quant','/encoder/encoder.1/mconv.6/conv/Conv_quant',
                           '/encoder/encoder.1/mconv.11/conv/Conv_quant','/encoder/encoder.1/mconv.16/conv/Conv_quant',
                           '/encoder/encoder.3/res.0.0/conv/Conv_quant','/encoder/encoder.4/mconv.16/conv/Conv_quant'])]:
    opt=ort.SessionOptions();opt.intra_op_num_threads=4;opt.inter_op_num_threads=1
    opt.add_session_config_entry('session.intra_op.allow_spinning','0')
    opt.add_session_config_entry('session.inter_op.allow_spinning','0')
    out=a.out.with_name(a.out.stem+'_'+name+'.onnx');out.parent.mkdir(parents=True,exist_ok=True)
    opt.optimized_model_filepath=str(out)
    g=candidate(m,nodes,quant=True) if nodes else onnx.shape_inference.infer_shapes(m)
    if nodes:opt.register_custom_ops_library(str(ROOT/'software/ort_fpga_bulk/libort_fpga.so'))
    runner=ort.InferenceSession(g.SerializeToString(),opt,providers=['CPUExecutionProvider'])
    optimized=onnx.load(str(out));counts=collections.Counter((n.domain+'.'+n.op_type) for n in optimized.graph.node)
    details=[{'name':n.name,'domain':n.domain,'type':n.op_type,'inputs':list(n.input),'outputs':list(n.output),
              'attributes':{a.name:str(onnx.helper.get_attribute_value(a)) for a in n.attribute}}
             for n in optimized.graph.node if 'Transpose' in n.op_type or 'Conv' in n.op_type or 'Pointwise' in n.op_type]
    rows[name]={'operator_counts':dict(counts),'optimized_graph_sha256':sha(out),'nodes':details}
    print(name,dict(counts),flush=True);del runner
write_json(a.out,{'scope':'Optimization inspection; no timed inference or accuracy claim','ort_version':ort.__version__,
                 'source_sha256':sha(__file__),'graphs':rows})
