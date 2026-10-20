"""Independent ORT pairs versus retained exact LUT/identity-stage arithmetic."""
import copy,ctypes,gc,sys
import numpy as np
import onnx
from onnx import helper,numpy_helper,TensorProto as T
from tail_benchmark import *
from split_scale_pairs import expand,TARGETS
from branch512_drop166_scale_benchmark import artifacts,bindings
qualified_items=artifacts()
sys.path.insert(0,str(ROOT/'software/ort_fpga_stream_branch512'))
from pair_graph import one_pair
from stream_graph import compile_chains
from probe import stats

original=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
producers={o:n for n in original.graph.node for o in n.output}
initializers={v.name:v for v in original.graph.initializer}
tiny_nodes=[];outputs=[];weights=[]
for pw in original.graph.node:
    if pw.name not in TARGETS:continue
    q=producers[pw.input[0]];where=producers[q.input[0]];dq=producers[where.input[2]];dw=producers[dq.input[0]]
    sequence=copy.deepcopy([dw,dq,where,q,pw]);sequence[0].input[0]='x';sequence[2].input[0]='mask'
    tiny_nodes.extend(sequence);outputs.append(helper.make_tensor_value_info(pw.output[0],T.UINT8,[1,256,'t']))
    weights.append((dw.name,pw.name))
used={i for n in tiny_nodes for i in n.input}
const=[copy.deepcopy(v) for name,v in initializers.items() if name in used]
constant_names={v.name for v in const}
for n in tiny_nodes:
    if n.op_type=='Where' and n.input[1] not in constant_names:
        producer=producers[n.input[1]];assert producer.op_type=='Constant'
        const.append(numpy_helper.from_array(numpy_helper.to_array(helper.get_attribute_value(producer.attribute[0])),n.input[1]))
        constant_names.add(n.input[1])
graph=helper.make_graph(tiny_nodes,'two-scale-changing-pairs',
    [helper.make_tensor_value_info('x',T.UINT8,[1,256,'t']),helper.make_tensor_value_info('mask',T.BOOL,[1,1,'t'])],outputs,const)
model=helper.make_model(graph,opset_imports=[helper.make_opsetid('',17)],ir_version=8)
onnx.checker.check_model(model)
expanded,_=expand(model)
for dw,pw in weights:
    stem=pw+'_scale_split'
    expanded=one_pair(expanded,dw,stem+'_identity_pw',True)
    expanded=one_pair(expanded,stem+'_identity_dw',pw,True)
retained,records=compile_chains(transform(expanded)[0],True)
assert len(records)==2 and all(len(r['pairs'])==2 for r in records)
for node in retained.graph.node:
    if node.domain=='prototype.fpga.stream.registered':
        node.domain='prototype.fpga.stream.branch512';node.op_type='FpgaChain'
retained.opset_import.append(helper.make_opsetid('prototype.fpga.stream.branch512',1))
library=ROOT/'software/ort_fpga_stream_branch512/libort_fpga.so';lib=ctypes.CDLL(str(library))
config={'threads':4,'spin':0,'level':'extended'}
reference=make_session(model,config)
runner=make_session(retained,config,[ROOT/'software/latency/libboundary_lut.so',library])
rng=np.random.default_rng(20261013);cases=[]
for times in (1,13,16,17,32,33,65,129,256):
    for valid in sorted({0,times//2,times}):
        for pattern in ('random','zero','maximum','alternating'):
            x=rng.integers(0,256,(1,256,times),dtype=np.uint8)
            if pattern=='zero':x.fill(0)
            if pattern=='maximum':x.fill(255)
            if pattern=='alternating':x[:]=((np.arange(256)[:,None]+np.arange(times)[None,:])%2*255).astype(np.uint8)
            mask=np.zeros((1,1,times),np.bool_);mask[:,:,valid:]=True
            feed={'x':x,'mask':mask};before=stats(lib)
            expected=reference.run(None,feed);actual=runner.run(None,feed);after=stats(lib)
            for a,b in zip(actual,expected):np.testing.assert_array_equal(a,b)
            assert after['physical_calls']-before['physical_calls']==4 and after['oracle_calls']==before['oracle_calls']==0
            cases.append({'times':times,'valid_times':valid,'pattern':pattern,'both_outputs_bit_exact':True})
    print('PASS scale pairs',times,flush=True)
write_json(ROOT/'reports/fused/branch512_drop166_scale_pairs_physical.json',{
    'complete':True,**bindings(qualified_items),'hardware_execution':True,'latency_measured':False,'cases':cases,'all_outputs_bit_exact':True,
    'input_contract':'Arbitrary UINT8 including nonzero masked suffix; mask applied at original boundary',
    'cpu_model_sha256':sha(ROOT/'research/fused/cpu-int8-cse.onnx'),'library_sha256':sha(library),
    'scale_split_source_sha256':sha(ROOT/'software/latency/split_scale_pairs.py'),'source_sha256':sha(__file__)})
print('PASS:',len(cases),'two-pair cases against original ORT convolutions',flush=True)
