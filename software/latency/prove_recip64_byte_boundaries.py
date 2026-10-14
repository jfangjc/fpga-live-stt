"""Compare every uint8 transition over the finite Float32 input domain.

For positive finite scales, both mappings are monotone: positive division or
double multiply, Float32 rounding, clamping, nearest-integer rounding and
zero-point addition. Equal first inputs producing each byte threshold prove
equal bytes for all finite Float32 inputs under the tested rounding mode.
This does not claim equal intermediate Float32 quotient values.
"""
import ctypes,json,struct,sys
from pathlib import Path
import numpy as np
import onnx
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
from common import sha,write_json
library=ROOT/'software/latency/libresidual_tail_recip64.so'
lib=ctypes.CDLL(str(library));assert lib.residual_tail_recip64_enabled()==1
libc=ctypes.CDLL(None);libc.fegetround.restype=ctypes.c_int
assert libc.fegetround()==0,'Proof requires round-to-nearest FP environment'
functions=[lib.residual_tail_divide_reference,lib.residual_tail_recip64_byte]
for function in functions:
    function.argtypes=(ctypes.c_float,ctypes.c_float,ctypes.c_uint32);function.restype=ctypes.c_uint32
model=ROOT/'research/fused/cpu-int8-cse.onnx'
arrays={v.name:onnx.numpy_helper.to_array(v) for v in onnx.load(model).graph.initializer}
parent=ROOT/'reports/fused/residual_tail_maskfast_validation.json'
records=json.loads(parent.read_text())['records']
def value(key):
    bits=key^0x80000000 if key&0x80000000 else (~key)&0xffffffff
    return struct.unpack('<f',struct.pack('<I',bits))[0]
rows=[]
for record in records:
    scale=float(arrays[record['inputs'][6]].item());zero=int(arrays[record['inputs'][7]].item())
    assert np.isfinite(scale) and scale>0 and 0<=zero<=255
    thresholds=[]
    for byte in range(1,256):
        starts=[]
        for function in functions:
            lo=0x00800000;hi=0xff800000 # [-max_float,+max_float], upper exclusive.
            assert function(value(lo),scale,zero)==0
            assert function(value(hi-1),scale,zero)==255
            while lo<hi:
                mid=(lo+hi)//2
                if function(value(mid),scale,zero)>=byte:hi=mid
                else:lo=mid+1
            assert function(value(lo),scale,zero)>=byte
            assert function(value(lo-1),scale,zero)<byte
            starts.append(lo)
        assert starts[0]==starts[1],(record['quantizer'],byte,starts)
        thresholds.append(starts[0])
    for bits in (0,0x80000000,0x7f800000,0xff800000,0x7fc00000,0xffc00000):
        x=struct.unpack('<f',struct.pack('<I',bits))[0]
        assert functions[0](x,scale,zero)==functions[1](x,scale,zero)
    rows.append({'quantizer':record['quantizer'],'scale':scale,'zero':zero,
                 'first_ordered_float_keys':thresholds,'all_byte_transitions_equal':True})
    print('PASS:',record['quantizer'],'255 byte boundaries',flush=True)
write_json(ROOT/'reports/fused/residual_tail_recip64_boundaries.json',{
    'complete':True,'hardware_execution':False,'rounding_mode':'FE_TONEAREST',
    'all_finite_float32_quantized_bytes_equal':True,'intermediate_quotients_claimed_equal':False,
    'regions':rows,'source_sha256':sha(__file__),'library_sha256':sha(library),
    'implementation_sha256':sha(ROOT/'software/latency/residual_tail_recip64.cc'),
    'model_sha256':sha(model),'parent_validation_sha256':sha(parent),
    'scope':'All finite Float32 values for the checkpoint output-scale/zero pairs; monotone byte-transition comparison; special-value spot checks'})
