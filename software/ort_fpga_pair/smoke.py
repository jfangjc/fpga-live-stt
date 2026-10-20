"""Exact isolated pair checks against independent NumPy arithmetic.

--physical requires the gated pair firmware and driver. No timing claim.
"""
import argparse,ctypes,sys
from pathlib import Path
import numpy as np
import onnx
from onnx import helper,numpy_helper
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
sys.path.insert(0,str(ROOT/'software/latency'))
from probe import session,stats
from common import sha,write_json
from validate_depthwise_pair import integer_conv


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--physical',action='store_true');ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();rng=np.random.default_rng(10102026)
    libpath=Path(__file__).with_name('libort_fpga.so');lib=ctypes.CDLL(str(libpath.resolve()))
    rows=[]
    for c,m,t,valid,zx,dzy,pzy in [(1,1,1,1,0,255,0),(3,17,17,13,255,0,255),
                                  (31,33,51,51,37,129,7),(256,256,51,51,128,127,128),
                                  (256,256,101,99,220,37,129),(80,640,33,0,0,255,255)]:
        arrays={'sx':np.array(.05,np.float32),'zx':np.array(zx,np.uint8),
                'dw':rng.integers(-127,128,(c,1,11),dtype=np.int8),
                'dws':rng.uniform(.001,.1,c).astype(np.float32),'dwz':np.array(0,np.int8),
                'ds':np.array(.13,np.float32),'dz':np.array(dzy,np.uint8),
                'db':rng.integers(-1000,1000,c,dtype=np.int32),
                'pw':rng.integers(-127,128,(m,c,1),dtype=np.int8),
                'pws':rng.uniform(.001,.1,m).astype(np.float32),'pwz':np.array(0,np.int8),
                'ps':np.array(.19,np.float32),'pz':np.array(pzy,np.uint8),
                'pb':rng.integers(-1000,1000,m,dtype=np.int32)}
        dw=helper.make_node('QLinearConv',['x','sx','zx','dw','dws','dwz','ds','dz','db'],['dy'],group=c,pads=[5,5])
        pw=helper.make_node('QLinearConv',['di','ds','dz','pw','pws','pwz','ps','pz','pb'],['y'])
        names=list(dw.input)+list(pw.input[3:])+['mask']
        x=rng.integers(0,256,(1,c,t),dtype=np.uint8);mask=np.arange(t)[None,None,:]>=valid
        dy=integer_conv(x,dw,arrays);di=np.where(mask,dzy,dy).astype(np.uint8)
        expected=integer_conv(di,pw,arrays)
        optypes=['oracle']+(['fpga'] if a.physical else [])
        for kind in optypes:
            node=helper.make_node('OracleDepthwisePointwise' if kind=='oracle' else 'FpgaDepthwisePointwise',
                                 names,['y'],domain='prototype.fpga.pair')
            g=helper.make_graph([node],'pair-smoke',
                               [helper.make_tensor_value_info('x',onnx.TensorProto.UINT8,[1,c,t]),
                                helper.make_tensor_value_info('mask',onnx.TensorProto.BOOL,[1,1,t])],
                               [helper.make_tensor_value_info('y',onnx.TensorProto.UINT8,[1,m,t])],
                               [numpy_helper.from_array(v,n) for n,v in arrays.items()])
            model=helper.make_model(g,opset_imports=[helper.make_opsetid('',17),helper.make_opsetid('prototype.fpga.pair',1)])
            model.ir_version=10;runner=session(model,libpath)
            for _ in range(2):
                before=stats(lib);actual=runner.run(None,{'x':x,'mask':mask})[0]
                delta={k:v-before[k] for k,v in stats(lib).items()}
                np.testing.assert_array_equal(actual,expected)
                assert delta['physical_calls']==(kind=='fpga') and delta['oracle_calls']==(kind=='oracle')
                rows.append({'channels':c,'outputs':m,'times':t,'valid_times':valid,'backend':kind,
                             'bit_exact':True,'counters':delta})
            del runner
        print('PASS',c,m,t,valid,flush=True)
    write_json(a.out,{'complete':True,'hardware_execution':a.physical,'exact_numpy_parity':True,
                     'source_sha256':sha(__file__),'library_sha256':sha(libpath),
                     'arithmetic_source_sha256':sha(ROOT/'software/latency/validate_depthwise_pair.py'),'cases':rows})


if __name__=='__main__':main()
