"""Original ORT pointwise tails versus retained identity-DW/PW programs."""
import copy,ctypes,sys
import numpy as np
import onnx
from onnx import helper,numpy_helper,TensorProto as T
from tail_benchmark import *
from retain_stride_pointwise import retain,TARGETS
from branch512_slice166_more_benchmark import artifacts,bindings
qualified_items=artifacts()
sys.path.insert(0,str(ROOT/'software/ort_fpga_stream_branch512'))
from stream_graph import compile_chains
from probe import stats
original=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
inits={v.name:v for v in original.graph.initializer}
nodes=[];inputs=[helper.make_tensor_value_info('mask',T.BOOL,[1,1,'t'])];outputs=[];constants=[]
zeros=[]
for index,pw in enumerate(n for n in original.graph.node if n.name in TARGETS):
    node=copy.deepcopy(pw);x='x'+str(index);zero=int(numpy_helper.to_array(inits[node.input[2]]));zeros.append(zero)
    lut=np.stack([np.arange(256,dtype=np.uint8),np.full(256,zero,np.uint8)])
    lut_name=x+'_table';constants.append(numpy_helper.from_array(lut,lut_name))
    nodes.append(helper.make_node('LookupMask',[x,'mask',lut_name],[node.input[0]],name=x+'_mask',domain='prototype.cpu.boundary'))
    nodes.append(node);inputs.append(helper.make_tensor_value_info(x,T.UINT8,[1,256,'t']))
    outputs.append(helper.make_tensor_value_info(node.output[0],T.UINT8,[1,256,'t']))
used={name for node in nodes for name in node.input}
constants.extend(copy.deepcopy(v) for name,v in inits.items() if name in used)
model=helper.make_model(helper.make_graph(nodes,'stride-pointwise-tails',inputs,outputs,constants),
    opset_imports=[helper.make_opsetid('',17),helper.make_opsetid('prototype.cpu.boundary',1)],ir_version=8)
onnx.checker.check_model(model)
retained,records=compile_chains(retain(model,True)[0],True)
assert len(records)==3 and all(len(r['pairs'])==1 for r in records)
for node in retained.graph.node:
    if node.domain=='prototype.fpga.stream.registered':
        node.domain='prototype.fpga.stream.branch512';node.op_type='FpgaChain'
retained.opset_import.append(helper.make_opsetid('prototype.fpga.stream.branch512',1))
library=ROOT/'software/ort_fpga_stream_branch512/libort_fpga.so';lib=ctypes.CDLL(str(library))
boundary=ROOT/'software/latency/libboundary_lut.so';config={'threads':4,'spin':0,'level':'extended'}
reference=make_session(model,config,[boundary]);runner=make_session(retained,config,[boundary,library])
rng=np.random.default_rng(202610131);cases=[]
for times in (1,13,16,17,32,33,65,129,256):
    for valid in sorted({0,times//2,times}):
        for pattern in ('random','zero','maximum','alternating'):
            mask=np.zeros((1,1,times),np.bool_);mask[:,:,valid:]=True;feed={'mask':mask}
            for i in range(3):
                x=rng.integers(0,256,(1,256,times),dtype=np.uint8)
                if pattern=='zero':x.fill(0)
                if pattern=='maximum':x.fill(255)
                if pattern=='alternating':x[:]=((np.arange(256)[:,None]+np.arange(times)[None,:])%2*255).astype(np.uint8)
                feed['x'+str(i)]=x
            before=stats(lib);expected=reference.run(None,feed);actual=runner.run(None,feed);after=stats(lib)
            for a,b in zip(actual,expected):np.testing.assert_array_equal(a,b)
            assert after['physical_calls']-before['physical_calls']==3 and after['oracle_calls']==before['oracle_calls']==0
            cases.append({'times':times,'valid_times':valid,'pattern':pattern,'all_three_outputs_bit_exact':True})
    print('PASS stride pointwise',times,flush=True)
write_json(ROOT/'reports/fused/branch512_slice166_more_pairs_physical.json',{'complete':True,**bindings(qualified_items),'hardware_execution':True,
    'latency_measured':False,'all_outputs_bit_exact':True,'cases':cases,
    'cpu_model_sha256':sha(ROOT/'research/fused/cpu-int8-cse.onnx'),'library_sha256':sha(library),
    'stride_tail_source_sha256':sha(ROOT/'software/latency/retain_stride_pointwise.py'),'source_sha256':sha(__file__)})
print('PASS:',len(cases),'three-tail cases against original ORT pointwise convolutions',flush=True)
