"""Portable host tests; no NumPy required. ARM64 NEON still needs board tests."""
import ctypes as C
import json
import random
import struct
from pathlib import Path

lib = C.CDLL(str(Path(__file__).parent / 'host/libqn_depthwise_x86_64.so'))
fn = lib.qn_depthwise_f32
P = C.POINTER(C.c_float)
fn.argtypes = [P, P, P, P] + [C.c_size_t] * 8 + [C.c_uint]
fn.restype = C.c_int
rng = random.Random(260)
def f32(x): return struct.unpack('=f', struct.pack('=f', x))[0]
def array(n): return (C.c_float*n)(*(rng.uniform(-1, 1) for _ in range(n)))

cases = [(1,1,33,1,1,1,0,0), (2,7,51,5,1,1,2,2),
         (1,3,501,87,1,1,43,43), (1,5,73,7,2,1,3,4),
         (3,2,39,3,1,3,8,1), (1,4,2,9,1,1,8,8),
         (1,1,1,1,1,1,0,0), (1,1,21,3,3,2,0,0)]
for _ in range(40):
    n,c,t,k = rng.randint(1,3),rng.randint(1,8),rng.randint(1,79),rng.randint(1,13)
    st,di = rng.randint(1,4),rng.randint(1,3)
    pl,pr = rng.randint(0,20),rng.randint(0,20)
    if t+pl+pr >= di*(k-1)+1: cases.append((n,c,t,k,st,di,pl,pr))
checked=0
for ci,dims in enumerate(cases):
    n,c,t,k,st,di,pl,pr=dims
    out=(t+pl+pr-di*(k-1)-1)//st+1
    x,w,b=array(n*c*t),array(c*k),array(c)
    bias = b if ci%2 else None
    expected=[]
    for batch in range(n):
      for channel in range(c):
        for o in range(out):
          a=0.0
          for ki in range(k):
            ix=o*st-pl+ki*di
            v=x[(batch*c+channel)*t+ix] if 0<=ix<t else 0.0
            a=f32(a+f32(v*w[channel*k+ki]))
          expected.append(f32(a+(b[channel] if bias is not None else 0.0)))
    for threads in (0,1,2,3,4,19):
        y=(C.c_float*(n*c*out))()
        ret=fn(x,w,bias,y,*dims,threads)
        assert ret==0,(ci,threads,ret)
        actual=list(y)
        assert actual==expected,(ci,threads,max(abs(a-b) for a,b in zip(actual,expected)))
        checked+=1
x,w,b,y=array(16),array(16),array(16),array(16)
base=(1,1,1,1,1,1,0,0)
invalid=[(0,1,1,1,1,1,0,0),(1,0,1,1,1,1,0,0),
         (1,1,1,1,0,1,0,0),(1,1,1,1,1,0,0,0),
         (1,1,1,3,1,1,0,0),(1,1,1,3,1,(1<<64)-1,0,0),
         ((1<<64)-1,2,1,1,1,1,0,0),(1,1,1,1,1,1,(1<<64)-1,0)]
for dims in invalid: assert fn(x,w,b,y,*dims,1)<0,dims
assert fn(None,w,b,y,*base,1)<0
assert fn(x,w,b,x,*base,1)<0
print(json.dumps({'result':'PASS','valid_shapes':len(cases),
                  'shape_thread_comparisons':checked,'reference':'unfused sequential FP32',
                  'invalid_requests':len(invalid)+2,
                  'arm64_neon_executed':False},indent=2))
