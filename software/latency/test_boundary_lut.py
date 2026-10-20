"""Verify ARM64 fast lookup, clamp, tails, and arbitrary mask fallbacks."""
import hashlib,json
from pathlib import Path
import numpy as np
import onnx
from onnx import helper,numpy_helper,TensorProto
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
rng=np.random.default_rng(20261012);library=ROOT/'software/latency/libboundary_lut.so'
checks=0
for kind in ('identity','clamp','lookup','general-mask'):
    base=np.arange(256,dtype=np.uint8)
    if kind=='clamp':base=np.clip(base,71,203).astype(np.uint8)
    elif kind in ('lookup','general-mask'):base=rng.permutation(base)
    masked=np.full(256,137,np.uint8) if kind!='general-mask' else rng.permutation(np.arange(256,dtype=np.uint8))
    lut=np.stack([base,masked])
    for t in (1,15,16,17,51,101,255,256):
        for mask_kind in ('none','all','suffix','random','scalar-true'):
            mt=1 if mask_kind in ('none','scalar-true') else t
            mask=np.zeros((1,1,mt),np.bool_)
            if mask_kind in ('all','scalar-true'):mask[:]=True
            elif mask_kind=='suffix':mask[:,:,t//2:]=True
            elif mask_kind=='random':mask[:]=rng.integers(0,2,mask.shape,dtype=np.uint8).astype(np.bool_)
            x=(np.arange(3*t,dtype=np.uint32)%256).astype(np.uint8).reshape(1,3,t)
            node=helper.make_node('LookupMask',['x','mask','lut'],['y'],domain='prototype.cpu.boundary')
            graph=helper.make_graph([node],'test',[helper.make_tensor_value_info('x',TensorProto.UINT8,[1,3,t]),
                    helper.make_tensor_value_info('mask',TensorProto.BOOL,[1,1,mt])],
                    [helper.make_tensor_value_info('y',TensorProto.UINT8,[1,3,t])],
                    [numpy_helper.from_array(lut,'lut')])
            model=helper.make_model(graph,opset_imports=[helper.make_opsetid('',17),helper.make_opsetid('prototype.cpu.boundary',1)])
            model.ir_version=9
            opt=ort.SessionOptions();opt.intra_op_num_threads=1;opt.register_custom_ops_library(str(library))
            runner=ort.InferenceSession(model.SerializeToString(),opt,providers=['CPUExecutionProvider'])
            actual=runner.run(None,{'x':x,'mask':mask})[0]
            expected=lut[np.broadcast_to(mask,x.shape).astype(np.int64),x]
            np.testing.assert_array_equal(actual,expected);checks+=1
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
print(json.dumps({'complete':True,'hardware_execution':False,'checks':checks,'all_bit_exact':True,
                  'library_sha256':digest(library),'source_sha256':digest(Path(__file__)),
                  'implementation_sha256':digest(ROOT/'software/latency/boundary_lut.cc')}))
