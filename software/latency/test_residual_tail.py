"""Compare fused tails with original ORT nodes, then full CPU model logits."""
import copy,json,sys
from pathlib import Path
import numpy as np
import onnx
from onnx import helper,TensorProto
from residual_tail import transform
from chain_benchmark import ROOT,make_session,read_audio,Frontend,corpus,sha,write_json
from boundary_lut import transform as boundaries
original=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
fused,records=transform(boundaries(original)[0]);assert len(records)>=8
library=ROOT/'software/latency/libresidual_tail.so'
libraries=[ROOT/'software/latency/libboundary_lut.so',library]
config={'threads':1,'spin':0,'level':'extended'}
nodes={n.name:n for n in original.graph.node}
constants={v.name:v for v in original.graph.initializer}
constant_nodes={o:n for n in original.graph.node if n.op_type=='Constant' for o in n.output}
rng=np.random.default_rng(20261012);checks=[]
for record in records:
    for times in (1,3,4,17,256):
        channels=3;inputs=record['inputs'];selected=[copy.deepcopy(n) for n in original.graph.node if n.name in record['nodes']]
        used={i for n in selected for i in n.input};initializer=[copy.deepcopy(constants[i]) for i in used if i in constants]
        selected=[copy.deepcopy(constant_nodes[i]) for i in used if i in constant_nodes]+selected
        values=[helper.make_tensor_value_info(name,kind,shape) for name,kind,shape in
                zip(inputs[:4],(TensorProto.FLOAT,TensorProto.FLOAT,TensorProto.UINT8,TensorProto.BOOL),
                    ([1,channels,times],[1,channels,1],[1,channels,times],[1,1,times]))]
        output=nodes[record['quantizer']].output[0]
        info=helper.make_tensor_value_info(output,TensorProto.UINT8,[1,channels,times])
        ref=helper.make_model(helper.make_graph(selected,'tail-reference',values,[info],initializer),opset_imports=[helper.make_opsetid('',17)])
        ref.ir_version=10
        custom=helper.make_node('ResidualTail',inputs,[output],domain='prototype.cpu.residual',relu=int(record['relu']))
        kept=[copy.deepcopy(constants[i]) for i in inputs[4:]]
        fast=helper.make_model(helper.make_graph([custom],'tail-fused',values,[info],kept),
                              opset_imports=[helper.make_opsetid('',17),helper.make_opsetid('prototype.cpu.residual',1)])
        fast.ir_version=10
        rr=make_session(ref,config);ff=make_session(fast,config,[library])
        x=rng.uniform(-50,50,(1,channels,times)).astype(np.float32)
        res=np.resize(np.arange(256,dtype=np.uint8),(1,channels,times))
        g=np.array([0,.5,1],np.float32).reshape(1,channels,1)
        for mask in (np.zeros((1,1,times),np.bool_),np.ones((1,1,times),np.bool_),rng.random((1,1,times))>.5):
            feed=dict(zip(inputs[:4],(x,g,res,mask)));expected=rr.run(None,feed)[0];actual=ff.run(None,feed)[0]
            np.testing.assert_array_equal(actual,expected)
            checks.append({'quantizer':record['quantizer'],'times':times,'masked':int(mask.sum()),'bit_exact':True})
reference=make_session(original,{'threads':4,'spin':10,'level':'extended'})
fast=make_session(fused,{'threads':4,'spin':10,'level':'extended'},libraries)
frontend=Frontend(ROOT/'research/export/citrinet-256-ls');full=[]
corpus_records=[]
for folder in ('user-recording','librispeech-mini','user-stress-ac'):
    corpus_records+=corpus(ROOT/'research/eval'/folder/'evaluation.jsonl',('evaluation','test'))
for item in corpus_records:
    audio=read_audio(item['path'])
    for seconds in (.25,.5,1,2):
        x,n=frontend(np.ascontiguousarray(audio[:round(seconds*16000)]));x=np.ascontiguousarray(x[:,:,:int(n[0])])
        feed={'features':x,'feature_lengths':n}
        expected=reference.run(None,feed);actual=fast.run(None,feed)
        for a,b in zip(actual,expected):np.testing.assert_array_equal(a,b)
        full.append({'audio':item['audio'],'seconds':seconds,'all_outputs_bit_exact':True})
write_json(ROOT/'reports/fused/residual_tail_validation.json',{'complete':True,'all_bit_exact':True,
           'library_sha256':sha(library),'source_sha256':sha(__file__),'implementation_sha256':sha(ROOT/'software/latency/residual_tail.cc'),
           'transform_sha256':sha(ROOT/'software/latency/residual_tail.py'),'cpu_model_sha256':sha(ROOT/'research/fused/cpu-int8-cse.onnx'),
           'records':records,'micro_cases':checks,'full_model_cases':full,'hardware_execution':False})
print('PASS:',len(checks),'original ORT tail cases and',len(full),'full CPU prefixes, all bit exact')
