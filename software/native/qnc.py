"""Single-call ctypes bridge. Native code owns all DMA packet loops and buffers."""
import ctypes as C
from pathlib import Path
import numpy as np

class Stats(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in ('ioctls','loads','runs','tx_bytes','rx_bytes')] + [('ioctl_seconds', C.c_double)]
class Profile(C.Structure):
    _fields_ = [(name,C.c_double) for name in ('load_pack_seconds','scan_seconds','run_pack_seconds','unpack_seconds')]

class NativeCachedDevice:
    def __init__(self, path='/dev/qn-tile', library=None):
        self.lib = C.CDLL(str(library or Path(__file__).with_name('libqnc.so')), use_errno=True)
        self.lib.qnc_open.argtypes = [C.c_char_p]
        self.lib.qnc_open.restype = C.c_void_p
        self.lib.qnc_close.argtypes = [C.c_void_p]
        self.lib.qnc_load.argtypes = [C.c_void_p,C.c_void_p,C.c_uint,C.c_uint]
        self.lib.qnc_run_i8.argtypes = [C.c_void_p,C.c_void_p,C.c_size_t,C.c_void_p]
        self.lib.qnc_run_f32.argtypes = [C.c_void_p,C.c_void_p,C.c_size_t,C.c_void_p,C.c_void_p,C.c_void_p]
        self.lib.qnc_invalidate.argtypes = [C.c_void_p]
        self.lib.qnc_get_stats.argtypes = [C.c_void_p,C.POINTER(Stats)]
        self.profile_getter=getattr(self.lib,'qnc_get_profile',None)
        if self.profile_getter:
            self.profile_getter.argtypes=[C.c_void_p,C.POINTER(Profile)]
        self.ctx = self.lib.qnc_open(path.encode())
        if not self.ctx:
            e = C.get_errno()
            raise OSError(e, 'qnc_open failed', path)
        self.loaded = None

    def _check(self, rc):
        if rc:
            self.loaded = None
            raise OSError(-rc, 'Native cached accelerator failed; command was not replayed')

    def load(self, weights):
        w = np.asarray(weights)
        if w.dtype != np.int8 or w.ndim != 2:
            raise ValueError('Expected INT8 W[M,K]')
        w = np.ascontiguousarray(w)
        self._check(self.lib.qnc_load(self.ctx,w.ctypes.data,*w.shape))
        self.loaded = (w.shape[1],w.shape[0])

    def run_many(self, inputs, outputs):
        x = np.asarray(inputs)
        if x.dtype != np.int8 or x.ndim != 2 or self.loaded != (x.shape[0],outputs):
            raise ValueError('Expected INT8 X[K,T] and successfully loaded matching weights')
        x = np.ascontiguousarray(x)
        y = np.empty((outputs,x.shape[1]),np.int32)
        self._check(self.lib.qnc_run_i8(self.ctx,x.ctypes.data,x.shape[1],y.ctypes.data))
        return y

    def run_float(self, inputs, weight_scales):
        x = np.ascontiguousarray(inputs,dtype=np.float32)
        scales = np.ascontiguousarray(weight_scales,dtype=np.float32)
        if x.ndim != 2 or self.loaded is None or x.shape[0] != self.loaded[0] or scales.shape != (self.loaded[1],):
            raise ValueError('Expected FP32 X[K,T] and weight scales[M]')
        y = np.empty((self.loaded[1],x.shape[1]),np.float32)
        activation_scale = C.c_float()
        self._check(self.lib.qnc_run_f32(self.ctx,x.ctypes.data,x.shape[1],scales.ctypes.data,y.ctypes.data,C.byref(activation_scale)))
        return y

    def stats(self):
        value = Stats()
        self.lib.qnc_get_stats(self.ctx,C.byref(value))
        result={name:getattr(value,name) for name,_ in value._fields_}
        if self.profile_getter:
            profile=Profile();self.profile_getter(self.ctx,C.byref(profile))
            result.update({name:getattr(profile,name) for name,_ in profile._fields_})
        return result

    def close(self):
        if self.ctx:
            self.lib.qnc_close(self.ctx)
            self.ctx = None
            self.loaded = None

    def __enter__(self): return self
    def __exit__(self,*args): self.close()
