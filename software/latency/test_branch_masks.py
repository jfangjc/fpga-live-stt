"""Compare two-output branch programs to ORT residual convs and prior body oracles."""
import copy,ctypes,gc,sys
import numpy as np
from tail_benchmark import *
sys.path.insert(0,str(ROOT/'software/ort_fpga_stream_branch'))
from branch_graph import compile_branches
from pair_graph import candidate as pairs
from stream_graph import compile_chains
from onnx import helper,numpy_helper,TensorProto as T
original=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
paired=transform(pairs(original,True)[0])[0]
body,_=compile_chains(paired,True);branches,records,bounds=compile_branches(paired,True)
body_nodes={n.name:n for n in body.graph.node};branch_nodes={n.name:n for n in branches.graph.node}
original_nodes={n.name:n for n in original.graph.node}
initializers={v.name:v for v in branches.graph.initializer}
for v in body.graph.initializer:initializers.setdefault(v.name,v)
for v in original.graph.initializer:initializers.setdefault(v.name,v)
libraries=[ROOT/'software/ort_fpga_stream_registered/libort_fpga.so',ROOT/'software/ort_fpga_stream_branch/libort_fpga.so']
config={'threads':4,'spin':0,'level':'extended'};rng=np.random.default_rng(2026101241);cases=[]
for record in records:
    old=copy.deepcopy(body_nodes[record['chain']]);new=copy.deepcopy(branch_nodes[record['chain']+'_residual_branch'])
    conv=copy.deepcopy(original_nodes[record['residual']])
    old.input[0]='x';old.input[1]='mask';old.output[0]='body_reference'
    new.input[0]='x';new.input[1]='mask';new.output[0]='body_branch';new.output[1]='residual_branch'
    conv.input[0]='x';conv.output[0]='residual_reference'
    outputs=[helper.make_tensor_value_info(name,T.UINT8,[1,256,'r' if name.startswith('residual') else 't'])
             for name in ('body_reference','body_branch','residual_reference','residual_branch')]
    names={name for node in (old,new,conv) for name in node.input if name not in ('x','mask')}
    graph=helper.make_graph([old,new,conv],'branch_mask_regression',
        [helper.make_tensor_value_info('x',T.UINT8,[1,256,'t']),helper.make_tensor_value_info('mask',T.BOOL,[1,1,'t'])],
        outputs,[initializers[name] for name in sorted(names)])
    model=helper.make_model(graph,opset_imports=[helper.make_opsetid('',17),
        helper.make_opsetid('prototype.fpga.stream.registered',1),helper.make_opsetid('prototype.fpga.stream.branch',1)],ir_version=8)
    runner=base_session(model,config,libraries)
    zero=int(numpy_helper.to_array(initializers[conv.input[2]]))
    for times in (1,13,17,65,256):
        for valid in sorted({0,times//2,times}):
            x=rng.integers(0,256,(1,256,times),dtype=np.uint8);mask=np.zeros((1,1,times),np.bool_)
            # Legal checkpoint boundaries encode invalid time positions as xzero.
            x[:,:,valid:]=zero;mask[:,:,valid:]=True
            a,b,c,d=runner.run(None,{'x':x,'mask':mask})
            np.testing.assert_array_equal(a,b);np.testing.assert_array_equal(c,d)
            cases.append({'residual':record['residual'],'times':times,'valid_times':valid,
                          'stride':record['residual_stride'],'all_outputs_bit_exact':True})
    print('PASS masked branch',record['residual'],flush=True)
    del runner;gc.collect()
write_json(ROOT/'reports/fused/branch_mask_validation.json',{'complete':True,'hardware_execution':False,
    'all_outputs_bit_exact':True,'cases':cases,'regions':len(records),'input_contract':'Invalid suffix bytes equal quantization zero',
    'library_sha256':sha(libraries[1]),'body_reference_library_sha256':sha(libraries[0]),
    'source_sha256':sha(__file__),'compiler_sha256':sha(ROOT/'software/ort_fpga_stream_branch/branch_graph.py')})
print('PASS:',len(cases),'masked two-output blocks against independent ORT residual projections',flush=True)
