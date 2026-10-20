"""Compare pooling bit patterns to original ORT operators and the full CPU model."""
import ctypes
import numpy as np
import onnx
from onnx import helper,numpy_helper,TensorProto as T
from tail_benchmark import *
from se_pool import transform as pool
library=ROOT/'software/latency/libse_pool.so';config={'threads':4,'spin':10,'level':'extended'}
lib=ctypes.CDLL(str(library));lib.se_pool_calls.restype=ctypes.c_uint64
def graph(native,c):
    initializers=[numpy_helper.from_array(np.array([-1 if c in (32,640) else 2],np.int64),'axis'),numpy_helper.from_array(np.array(0,np.float32),'zero')]
    if native:nodes=[helper.make_node('MaskedSEMean',['x','mask','axis'],['masked','mean'],domain='prototype.cpu.se_pool')]
    else:nodes=[helper.make_node('Where',['mask','zero','x'],['masked']),
                helper.make_node('Not',['mask'],['valid']),helper.make_node('Cast',['valid'],['valid_int'],to=T.INT64),
                helper.make_node('ReduceSum',['valid_int','axis'],['count'],keepdims=1),
                helper.make_node('Cast',['count'],['den'],to=T.FLOAT),
                helper.make_node('ReduceSum',['masked','axis'],['sum'],keepdims=1),
                helper.make_node('Div',['sum','den'],['mean'])]
    g=helper.make_graph(nodes,'pooling',[helper.make_tensor_value_info('x',T.FLOAT,[1,c,'t']),
                        helper.make_tensor_value_info('mask',T.BOOL,[1,1,'t'])],
                       [helper.make_tensor_value_info('masked',T.FLOAT,[1,c,'t']),
                        helper.make_tensor_value_info('mean',T.FLOAT,[1,c,1])],initializers)
    return helper.make_model(g,opset_imports=[helper.make_opsetid('',17),helper.make_opsetid('prototype.cpu.se_pool',1)],ir_version=8)
rng=np.random.default_rng(20261012);micro=[]
for channels in (1,32,256,640):
    reference=make_session(graph(False,channels),config)
    native=make_session(graph(True,channels),config,[library])
    for times in (1,7,13,16,17,32,51,65,101,256):
        for kind in ('full','half','empty','random'):
            x=(rng.integers(-128,128,(1,channels,times)).astype(np.float32)*np.float32(.01739)).astype(np.float32)
            mask=np.zeros((1,1,times),dtype=np.bool_)
            if kind=='half':mask[:,:,times//2:]=True
            if kind=='empty':mask[:]=True
            if kind=='random':mask[:]=rng.integers(0,2,mask.shape).astype(np.bool_)
            x[0,0,0]=np.float32(-0.)
            if times>1:x[0,0,-1]=np.float32(np.nan)
            expected=reference.run(None,{'x':x,'mask':mask});actual=native.run(None,{'x':x,'mask':mask})
            for a,b in zip(actual,expected):np.testing.assert_array_equal(a.view(np.uint32),b.view(np.uint32))
            micro.append({'channels':channels,'times':times,'mask':kind,'all_float_bits_exact':True})
    print('PASS native pooling channels',channels,flush=True)
original=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
fused,records=pool(tails(transform(original)[0])[0])
reference=make_session(original,config);native=make_session(fused,config,[ROOT/'software/latency/libboundary_lut.so',library])
frontend=Frontend(ROOT/'research/export/citrinet-256-ls');full=[];records_audio=[]
for folder in ('user-recording','librispeech-mini','user-stress-ac'):
    records_audio+=corpus(ROOT/'research/eval'/folder/'evaluation.jsonl',('evaluation','test'))
for record in records_audio:
    audio=read_audio(record['path'])
    for seconds in (.25,.5,1,2):
        x,n=frontend(np.ascontiguousarray(audio[:round(seconds*16000)]));x=np.ascontiguousarray(x[:,:,:int(n[0])])
        feed={'features':x,'feature_lengths':n};expected=reference.run(None,feed);before=lib.se_pool_calls();actual=native.run(None,feed)
        assert lib.se_pool_calls()-before==21
        for a,b in zip(actual,expected):np.testing.assert_array_equal(a,b)
        full.append({'id':record['id'],'seconds':seconds,'all_outputs_bit_exact':True})
write_json(ROOT/'reports/fused/se_pool_validation.json',{'complete':True,'hardware_execution':False,'all_bit_exact':True,
          'micro_cases':micro,'full_model_cases':full,'regions':records,'library_sha256':sha(library),
          'implementation_sha256':sha(ROOT/'software/latency/se_pool.cc'),'transform_sha256':sha(ROOT/'software/latency/se_pool.py'),
          'source_sha256':sha(__file__),'cpu_model_sha256':sha(ROOT/'research/fused/cpu-int8-cse.onnx')})
print('PASS:',len(micro),'floating bit-pattern tests and',len(full),'full CPU prefixes',flush=True)
