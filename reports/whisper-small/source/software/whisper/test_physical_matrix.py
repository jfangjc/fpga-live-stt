"""Physical QNC2 arithmetic conformance for Whisper matrix tile shapes.

Run only with the bulk image/driver active. Includes full INT8 extremes and
time/output tails, then validates INT32 results against independent NumPy INT64.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import numpy as np


class Stats(C.Structure):
    _fields_ = [(n, C.c_uint64) for n in ('ioctls', 'loads', 'runs', 'tx_bytes', 'rx_bytes')] + [('ioctl_seconds', C.c_double)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--library', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--ggml', action='store_true')
    a = ap.parse_args()
    if a.out.exists():
        ap.error('Refusing to overwrite evidence')
    if Path('/sys/module/qn_tile/parameters/bulk_protocol').read_text().strip() != '1':
        raise RuntimeError('Matching bulk driver required')
    lib = C.CDLL(str(a.library.resolve()))
    lib.qnc_open.argtypes = [C.c_char_p]
    lib.qnc_open.restype = C.c_void_p
    lib.qnc_close.argtypes = [C.c_void_p]
    lib.qnc_load.argtypes = [C.c_void_p, C.c_void_p, C.c_uint, C.c_uint]
    lib.qnc_run_i8.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_void_p]
    lib.qnc_get_stats.argtypes = [C.c_void_p, C.POINTER(Stats)]
    device = lib.qnc_open(b'/dev/qn-tile')
    if not device:
        raise RuntimeError('Cannot open physical FPGA')
    rng = np.random.default_rng(260)
    rows = []
    try:
        for m,k,t in [(64,64,17), (512,512,31), (1024,512,17), (512,1024,17), (65,67,19), (512,512,1500), (1024,1024,1500)]:
            w = rng.integers(-128,128,(m,k),dtype=np.int16).astype(np.int8)
            x = rng.integers(-128,128,(k,t),dtype=np.int16).astype(np.int8)
            y = np.empty((m,t),dtype=np.int32)
            start = time.perf_counter()
            rc = lib.qnc_load(device,w.ctypes.data,m,k)
            if not rc:
                rc = lib.qnc_run_i8(device,x.ctypes.data,t,y.ctypes.data)
            elapsed = time.perf_counter()-start
            if rc:
                raise RuntimeError(f'Physical DMA failure: {rc}')
            expected = w.astype(np.int64) @ x.astype(np.int64)
            np.testing.assert_array_equal(y, expected)
            rows.append({'m':m,'k':k,'t':t,'exact_int32':True,'physical_seconds':elapsed})
            print(rows[-1],flush=True)
        if a.ggml:
            lib.qnc_run_ggml.argtypes = [C.c_void_p,C.c_void_p,C.c_size_t,C.c_size_t,C.c_void_p,C.c_void_p,C.c_size_t]
            for m,k,t in [(65,67,19),(512,1024,17),(1024,64,1500)]:
                w = rng.integers(-128,128,(m,k),dtype=np.int16).astype(np.int8)
                x = rng.normal(size=(t,k+3)).astype(np.float32)
                x *= np.geomspace(0.001,1000,t,dtype=np.float32)[:,None]
                x[0,:k] = 0
                x[0,:6] = [0.5,1.5,-0.5,-1.5,127,-127]
                x[1,:k] = 0
                sw = rng.uniform(0.001,0.02,m).astype(np.float32)
                y = rng.normal(size=(t,m+5)).astype(np.float32)
                original = y.copy()
                sx = np.max(np.abs(x[:,:k]),axis=1)/np.float32(127)
                sx[sx==0] = 1
                qx = np.clip(np.rint(x[:,:k]/sx[:,None]),-127,127).astype(np.int8)
                acc = qx.astype(np.int64) @ w.astype(np.int64).T
                expected = original[:,:m] + acc.astype(np.float32)*(sx[:,None]*sw[None,:])
                rc = lib.qnc_load(device,w.ctypes.data,m,k)
                if not rc:
                    rc = lib.qnc_run_ggml(device,x.ctypes.data,k+3,t,sw.ctypes.data,y.ctypes.data,m+5)
                if rc:
                    raise RuntimeError(f'GGML physical DMA failure: {rc}')
                np.testing.assert_array_equal(y[:,:m],expected)
                np.testing.assert_array_equal(y[:,m:],original[:,m:])
                rows.append({'m':m,'k':k,'t':t,'ggml_per_column_float_exact':True})
                print(rows[-1],flush=True)
            barrier_type = C.CFUNCTYPE(None,C.c_void_p)
            barrier = threading.Barrier(4)
            @barrier_type
            def synchronize(opaque):
                barrier.wait(timeout=30)
            lib.qnc_run_ggml_parallel.argtypes = [C.c_void_p,C.c_void_p,C.c_size_t,C.c_size_t,
                C.c_void_p,C.c_void_p,C.c_size_t,C.c_int,C.c_uint,C.c_uint,barrier_type,C.c_void_p]
            y.fill(123)
            def worker(ith):
                return lib.qnc_run_ggml_parallel(device,x.ctypes.data,k+3,t,sw.ctypes.data,
                    y.ctypes.data,m+5,0,ith,4,synchronize,None)
            with ThreadPoolExecutor(max_workers=4) as workers:
                statuses = list(workers.map(worker,range(4)))
            if statuses != [0]*4:
                raise RuntimeError(f'Parallel physical path failed: {statuses}')
            np.testing.assert_array_equal(y[:,:m],acc.astype(np.float32)*(sx[:,None]*sw[None,:]))
            np.testing.assert_array_equal(y[:,m:],np.float32(123))
            rows.append({'m':m,'k':k,'t':t,'ggml_parallel_4_exact':True,'first_tile_overwrites':True})
            print(rows[-1],flush=True)
            before = Stats()
            lib.qnc_get_stats(device,C.byref(before))
            x[-1,0] = np.nan
            if lib.qnc_run_ggml(device,x.ctypes.data,k+3,t,sw.ctypes.data,y.ctypes.data,m+5) != -33:
                raise RuntimeError('Expected -EDOM for NaN')
            after = Stats()
            lib.qnc_get_stats(device,C.byref(after))
            if after.ioctls != before.ioctls:
                raise RuntimeError('Nonfinite input reached physical DMA')
        stats = Stats()
        lib.qnc_get_stats(device,C.byref(stats))
        if min(stats.loads,stats.runs,stats.ioctls) == 0:
            raise RuntimeError('Missing physical execution counters')
        report = {'passed':True,'cases':rows,'stats':{name:getattr(stats,name) for name,_ in stats._fields_}}
        a.out.write_text(json.dumps(report,indent=2)+'\n')
    finally:
        lib.qnc_close(device)


if __name__ == '__main__':
    main()
