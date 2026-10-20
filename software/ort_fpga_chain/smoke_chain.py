"""Independent NumPy checks for retained chains, including feedback and masks."""
import argparse,ctypes,json,struct,sys
from pathlib import Path
import numpy as np
import onnx
from onnx import helper,numpy_helper
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
sys.path.insert(0,str(ROOT/'software/latency'))
from common import sha,write_json
from probe import session,stats
from validate_depthwise_pair import integer_conv
ap=argparse.ArgumentParser();ap.add_argument('--physical',action='store_true');ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
library=Path(__file__).with_name('libort_fpga.so');lib=ctypes.CDLL(str(library));rng=np.random.default_rng(20261012)
rows=[]
for base_kernel in (11,13,15,17,19,21):
    for count in (1,2,5):
        stages=[];payload=bytearray(struct.pack('<II',0x314e4843,count))
        for i in range(count):
            kernel=11+2*(((base_kernel-11)//2+i)%6)
            zx=(0,255,37,220,128)[i];dzy=(255,0,129,37,127)[i];pzy=(0,255,7,129,128)[i]
            arrays={'sx':np.array(.05,np.float32),'zx':np.array(zx,np.uint8),
                    'dw':rng.integers(-127,128,(256,1,kernel),dtype=np.int8),
                    'dws':rng.uniform(.001,.1,256).astype(np.float32),'dwz':np.array(0,np.int8),
                    'ds':np.array(.13,np.float32),'dz':np.array(dzy,np.uint8),
                    'db':rng.integers(-1000,1000,256,dtype=np.int32),
                    'pw':rng.integers(-127,128,(256,256,1),dtype=np.int8),
                    'pws':rng.uniform(.001,.1,256).astype(np.float32),'pwz':np.array(0,np.int8),
                    'ps':np.array(.19,np.float32),'pz':np.array(pzy,np.uint8),
                    'pb':rng.integers(-1000,1000,256,dtype=np.int32)}
            dw=helper.make_node('QLinearConv',['x','sx','zx','dw','dws','dwz','ds','dz','db'],['dy'],group=256,pads=[kernel//2]*2)
            pw=helper.make_node('QLinearConv',['di','ds','dz','pw','pws','pwz','ps','pz','pb'],['y'])
            lut=rng.permutation(np.arange(256,dtype=np.uint8));masked=int(rng.integers(0,256))
            stages.append((arrays,dw,pw,lut,masked))
            payload.extend(struct.pack('<IIIIfff',kernel,zx,dzy,pzy,.05,.13,.19))
            for name,dtype in (('dws','<f4'),('pws','<f4'),('db','<i4'),('pb','<i4'),('dw','i1'),('pw','i1')):
                payload.extend(np.ascontiguousarray(arrays[name],dtype=dtype).tobytes())
            payload.extend(lut.tobytes());payload.extend(struct.pack('<I',masked))
        runners={}
        for kind in ('oracle','fpga') if a.physical else ('oracle',):
            node=helper.make_node('OracleChain' if kind=='oracle' else 'FpgaChain',['x','mask','program'],['y'],domain='prototype.fpga.chain')
            graph=helper.make_graph([node],'chain-smoke',
                    [helper.make_tensor_value_info('x',onnx.TensorProto.UINT8,[1,256,'T']),
                     helper.make_tensor_value_info('mask',onnx.TensorProto.BOOL,[1,1,'T'])],
                    [helper.make_tensor_value_info('y',onnx.TensorProto.UINT8,[1,256,'T'])],
                    [numpy_helper.from_array(np.frombuffer(payload,dtype=np.uint8).copy(),'program')])
            model=helper.make_model(graph,opset_imports=[helper.make_opsetid('',17),helper.make_opsetid('prototype.fpga.chain',1)])
            model.ir_version=10;runners[kind]=session(model,library)
        for t in (1,17,65,256):
            for valid in (0,t):
                x=rng.integers(0,256,(1,256,t),dtype=np.uint8);mask=np.arange(t)[None,None,:]>=valid
                expected=x.copy()
                for i,(arrays,dw,pw,lut,masked) in enumerate(stages):
                    intermediate=integer_conv(expected,dw,arrays)
                    intermediate=np.where(mask,int(arrays['dz']),intermediate).astype(np.uint8)
                    expected=integer_conv(intermediate,pw,arrays)
                    if i<count-1:expected=np.where(mask,masked,lut[expected]).astype(np.uint8)
                for kind,runner in runners.items():
                    for repeat in range(2):
                        before=stats(lib);actual=runner.run(None,{'x':x,'mask':mask})[0]
                        delta={k:v-before[k] for k,v in stats(lib).items()}
                        np.testing.assert_array_equal(actual,expected)
                        assert delta['physical_calls']==(count if kind=='fpga' else 0)
                        assert delta['oracle_calls']==(count if kind=='oracle' else 0)
                        if kind=='fpga' and repeat:assert delta['loads']==0 and delta['ioctls']==1
                        rows.append({'base_kernel':base_kernel,'chain_length':count,'times':t,'valid_times':valid,
                                     'backend':kind,'repeat':repeat,'bit_exact':True,'counters':delta})
                print('PASS',base_kernel,count,t,valid,flush=True)
        del runner,runners
write_json(a.out,{'complete':True,'hardware_execution':a.physical,'exact_numpy_parity':True,
                 'source_sha256':sha(__file__),'library_sha256':sha(library),
                 'arithmetic_source_sha256':sha(ROOT/'software/latency/validate_depthwise_pair.py'),'cases':rows})
