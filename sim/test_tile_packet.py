"""Independent software transport emulation checks padding, layout and K chunks."""
import pathlib
import struct
import sys
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'software'))
from qn_tile import packet, pointwise


def emulate(data):
    magic, k, r0, r1 = struct.unpack('<IIII', data[:16])
    assert magic == 0x31544E51 and r0 == r1 == 0
    assert len(data) == 16 + 32*k
    x = np.frombuffer(data[16:16+16*k], np.int8).reshape(k,16).astype(np.int64)
    w = np.frombuffer(data[16+16*k:], np.int8).reshape(k,16).astype(np.int64)
    return (x.T @ w).astype('<i4').tobytes()


rng = np.random.default_rng(260)
for k, times, outputs in [(1,1,1),(17,31,19),(1024,16,16),(1031,33,17)]:
    x = rng.integers(-128,128,(k,times),dtype=np.int8)
    w = rng.integers(-128,128,(outputs,k),dtype=np.int8)
    actual = pointwise(x,w,emulate)
    np.testing.assert_array_equal(actual,w.astype(np.int64) @ x.astype(np.int64))
for value in [-128,127]:
    x = np.full((2048,17), value,np.int8)
    w = np.full((19,2048), value,np.int8)
    np.testing.assert_array_equal(pointwise(x,w,emulate),w.astype(np.int64) @ x.astype(np.int64))
try:
    packet(np.ones((2,2),np.float32),np.ones((2,2),np.int8))
except TypeError:
    pass
else:
    raise AssertionError('Float inputs silently accepted')
print('PASS: tile layout, signed extrema, padding, multi-tile scheduling and K chunk accumulation')
