"""Blocking FP32 depthwise 1D Conv binding for the optional native CPU kernel."""
import ctypes
import hashlib
from pathlib import Path
import numpy as np


class NativeDepthwise:
    def __init__(self, library=None, threads=4):
        if not 1 <= threads <= 4:
            raise ValueError('Native CPU Conv threads must be 1..4')
        directory = Path(__file__).resolve().parent/'native'
        self.path = Path(library) if library else directory/'libqn_depthwise.so'
        if library is None and not self.path.exists():
            self.path = directory/'prebuilt/libqn_depthwise_aarch64.so'
        self.library = ctypes.CDLL(str(self.path))
        self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.threads = threads
        self.calls = 0
        self.function = self.library.qn_depthwise_f32
        pointer = ctypes.POINTER(ctypes.c_float)
        self.function.argtypes = [pointer]*4 + [ctypes.c_size_t]*8 + [ctypes.c_uint]
        self.function.restype = ctypes.c_int

    def __call__(self, x, w, bias, attrs):
        if x.dtype != np.float32 or w.dtype != np.float32 or x.ndim != 3 or w.ndim != 3:
            raise ValueError('Native Conv requires FP32 NCT inputs and [C,1,K] weights')
        n, c, t = x.shape
        if w.shape[:2] != (c,1) or attrs.get('group',1) != c:
            raise ValueError('Native Conv supports depthwise multiplier 1 only')
        if attrs.get('auto_pad',b'NOTSET') not in (b'NOTSET',b''):
            raise ValueError('Native Conv requires explicit padding')
        stride, = attrs.get('strides',[1])
        dilation, = attrs.get('dilations',[1])
        left, right = attrs.get('pads',[0,0])
        k = w.shape[2]
        if attrs.get('kernel_shape',[k]) != [k]:
            raise ValueError('Native Conv kernel shape mismatch')
        if min(n,c,t,k,stride,dilation) < 1 or min(left,right) < 0:
            raise ValueError('Invalid native Conv dimensions')
        extent = dilation*(k-1)+1
        out_t = (t+left+right-extent)//stride+1
        if out_t < 1:
            raise ValueError('Native Conv output is empty')
        x = np.ascontiguousarray(x)
        w = np.ascontiguousarray(w)
        if bias is not None:
            if bias.dtype != np.float32 or bias.shape != (c,):
                raise ValueError('Native Conv bias must be FP32 [C]')
            bias = np.ascontiguousarray(bias)
        y = np.empty((n,c,out_t),dtype=np.float32)
        pointer = ctypes.POINTER(ctypes.c_float)
        status = self.function(x.ctypes.data_as(pointer),w.ctypes.data_as(pointer),
                               bias.ctypes.data_as(pointer) if bias is not None else None,
                               y.ctypes.data_as(pointer),n,c,t,k,stride,dilation,left,right,
                               self.threads)
        if status:
            raise RuntimeError(f'Native CPU Conv failed with status {status}')
        self.calls += 1
        return y
