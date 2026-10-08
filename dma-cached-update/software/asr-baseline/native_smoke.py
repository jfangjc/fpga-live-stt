#!/usr/bin/env python3
"""Validate native depthwise arithmetic before using it in the hybrid model."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from native_depthwise import NativeDepthwise


def reference(x,w,bias,attrs):
    left,right = attrs['pads']
    stride, = attrs['strides']
    dilation, = attrs['dilations']
    padded = np.pad(x,((0,0),(0,0),(left,right)))
    extent = dilation*(w.shape[2]-1)+1
    windows = np.lib.stride_tricks.sliding_window_view(padded,extent,axis=2)[:,:,::stride,::dilation]
    y = np.einsum('nctk,ck->nct',windows,w[:,0],dtype=np.float32,optimize=False)
    return y if bias is None else y+bias[None,:,None]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',type=Path)
    parser.add_argument('--report',type=Path,default=Path('native-smoke.json'))
    args = parser.parse_args()
    rng = np.random.default_rng(3507)
    checks = 0
    max_error = 0.
    kernels = {threads:NativeDepthwise(args.library,threads) for threads in (1,4)}
    for n,c,t,k,stride,dilation,left,right in (
        (2,7,55,1,1,1,0,0), (1,1,17,3,1,1,1,1),
        (1,7,67,7,1,2,7,5), (2,9,91,9,2,1,4,4),
        (1,4,31,5,3,2,3,6), (1,7,3,9,1,1,8,8),
        (1,512,500,87,1,1,43,43), (1,64,1000,33,2,1,16,16)):
        x = rng.standard_normal((n,c,t),dtype=np.float32)
        w = rng.standard_normal((c,1,k),dtype=np.float32)
        attrs = {'group':c,'pads':[left,right],'strides':[stride],'dilations':[dilation]}
        for bias in (None,rng.standard_normal(c,dtype=np.float32)):
            expected = reference(x,w,bias,attrs)
            scale = max(1.,float(np.max(np.abs(expected))))
            for threads,kernel in kernels.items():
                actual = kernel(x,w,bias,attrs)
                error = float(np.max(np.abs(expected-actual)))/scale
                if actual.shape != expected.shape or not np.all(np.isfinite(actual)) or error > 5e-6:
                    raise AssertionError((n,c,t,k,threads,error))
                max_error = max(max_error,error)
                checks += 1
    # Representative late encoder layer. Warm both kernels, use medians.
    x = rng.standard_normal((1,512,500),dtype=np.float32)
    w = rng.standard_normal((512,1,87),dtype=np.float32)
    bias = rng.standard_normal(512,dtype=np.float32)
    attrs = {'group':512,'pads':[43,43],'strides':[1],'dilations':[1]}
    timings = {}
    for name,fn in [('numpy',reference)]+[(f'native_{t}_threads',f) for t,f in kernels.items()]:
        fn(x,w,bias,attrs)
        elapsed = []
        for _ in range(5):
            started = time.perf_counter()
            fn(x,w,bias,attrs)
            elapsed.append(time.perf_counter()-started)
        timings[name] = float(np.median(elapsed))
    report = {'result':'PASS','fpga_execution':False,'cpu_kernel_execution':True,
              'checks':checks,'max_scaled_error':max_error,
              'library_sha256':kernels[1].sha256,'representative_layer_seconds':timings,
              'note':'CPU arithmetic tolerance checks; not full ASR accuracy or FPGA performance validation'}
    args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
