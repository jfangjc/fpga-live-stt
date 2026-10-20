"""Physical fused-output arithmetic and overflow recovery smoke."""
import argparse,ctypes,time
from pathlib import Path
import numpy as np
from onnx import helper,numpy_helper,TensorProto
from probe import ROOT,session,stats
from common import sha,write_json


def graph(w,b,zx,zy,sx,sw,t,oracle=False):
    m,k=w.shape
    init=[numpy_helper.from_array(v,n) for n,v in (
        ('sx',np.array(sx,np.float32)),('zx',np.array(zx,np.uint8)),
        ('w',w[:,:,None]),('sw',sw),('zw',np.zeros(m,np.int8)),
        ('sy',np.array(1/256,np.float32)),('zy',np.array(zy,np.uint8)),('bias',b))]
    node=helper.make_node('OracleBulkPointwise' if oracle else 'FpgaBulkPointwise',
                          ['x','sx','zx','w','sw','zw','sy','zy','bias'],['y'],
                          name='physical-smoke',domain='prototype.fpga',stride=1)
    return helper.make_model(helper.make_graph([node],'quant-smoke',
        [helper.make_tensor_value_info('x',TensorProto.UINT8,[1,k,t])],
        [helper.make_tensor_value_info('y',TensorProto.UINT8,[1,m,t])],init),
        opset_imports=[helper.make_opsetid('',17),helper.make_opsetid('prototype.fpga',1)],ir_version=10)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--library',type=Path,default=Path(__file__).with_name('libort_fpga.so'))
    p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    lib=ctypes.CDLL(str(args.library.resolve()));rng=np.random.default_rng(7726)
    before=stats(lib);checks=[]
    for m,k,t,zx,zy in [(1,1,1,0,0),(17,31,17,255,255),(256,80,129,128,127),
                         (256,256,1008,37,129),(640,256,127,220,7),(1024,1024,33,128,128)]:
        w=rng.integers(-128,128,(m,k),dtype=np.int8)
        b=rng.integers(-100000,100000,m,dtype=np.int32)
        x=rng.integers(0,256,(1,k,t),dtype=np.uint8)
        sw=np.exp2(rng.integers(-16,-7,m)).astype(np.float32)
        cpu=session(graph(w,b,zx,zy,1/128,sw,t,True),args.library)
        fpga=session(graph(w,b,zx,zy,1/128,sw,t),args.library)
        expected=cpu.run(None,{'x':x})[0]
        start=time.perf_counter();actual=fpga.run(None,{'x':x})[0]
        elapsed=time.perf_counter()-start
        np.testing.assert_array_equal(actual,expected)
        checks.append({'m':m,'k':k,'times':t,'input_zero_point':zx,'output_zero_point':zy,
                       'physical_oracle_exact':True,'cold_load_and_run_seconds':elapsed})
        del cpu,fpga
    # Overflow must fail rather than wrap or replay on CPU. A subsequent fresh
    # LOAD must recover through the matching driver's reset/invalidation path.
    w=np.ones((1,1),np.int8);b=np.array([2**31-1],np.int32);sw=np.array([1/256],np.float32)
    bad=session(graph(w,b,128,128,1,sw,1),args.library)
    try:bad.run(None,{'x':np.array([[[129]]],np.uint8)})
    except Exception as e:
        if 'FPGA transport/protocol failed' not in str(e):raise
        checks.append({'late_overflow_rejected_without_cpu_fallback':True})
    else:raise AssertionError('Physical overflow was silently accepted')
    del bad
    good=session(graph(w,np.zeros(1,np.int32),128,128,1,sw,1),args.library)
    actual=good.run(None,{'x':np.array([[[129]]],np.uint8)})[0]
    np.testing.assert_array_equal(actual,np.array([[[129]]],np.uint8))
    checks.append({'fresh_load_recovers_after_error':True})
    after=stats(lib)
    write_json(args.out,{'hardware_execution':True,'checks':checks,
                        'library_sha256':sha(args.library),
                        'stats_delta':{k:after[k]-before[k] for k in after}})
    print('PASS: physical fused output parity, asymmetric zero points, large shapes and error recovery',flush=True)


if __name__=='__main__':main()
