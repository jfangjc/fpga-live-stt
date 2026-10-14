"""Physical QNC2 arithmetic smoke; must run after matching firmware/driver load."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from qnc import NativeCachedDevice

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--device',default='/dev/qn-tile')
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    rng=np.random.default_rng(2026);checks=[]
    with NativeCachedDevice(args.device) as device:
        for m,k,t in [(1,1,1),(17,31,17),(256,64,129),(1024,1024,33)]:
            w=rng.integers(-128,128,size=(m,k),dtype=np.int8)
            x=rng.integers(-128,128,size=(k,t),dtype=np.int8)
            expected=w.astype(np.int64)@x.astype(np.int64)
            start=time.perf_counter();device.load(w);actual=device.run_many(x,m);elapsed=time.perf_counter()-start
            np.testing.assert_array_equal(actual.astype(np.int64),expected)
            checks.append({'m':m,'k':k,'times':t,'exact_integer_match':True,'load_and_run_seconds':elapsed})
        w=np.array([[1,-2],[3,4]],np.int8);x=rng.normal(size=(2,35)).astype(np.float32);scales=np.array([.25,.5],np.float32)
        act=np.float32(np.max(np.abs(x))/np.float32(127))
        qx=np.clip(np.rint(x/act),-127,127).astype(np.int8)
        expected=(w.astype(np.int32)@qx.astype(np.int32)).astype(np.float32)*(scales*act)[:,None]
        device.load(w);actual=device.run_float(x,scales)
        np.testing.assert_array_equal(actual,expected)
        checks.append({'fused_float_scaling_exact':True})
        device._check(device.lib.qnc_invalidate(device.ctx));device.loaded=None
        try: device.run_many(np.ones((2,1),np.int8),2)
        except ValueError: checks.append({'run_after_invalidate_rejected':True})
        else: raise AssertionError('Invalidated cache accepted RUN')
        report={'hardware_execution':True,'device':args.device,'checks':checks,'stats':device.stats(),
                'native_library_sha256':hashlib.sha256(Path(__file__).with_name('libqnc.so').read_bytes()).hexdigest(),
                'limits':['Arithmetic smoke does not establish model WER, speedup or sustained capture']}
    args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__': main()
