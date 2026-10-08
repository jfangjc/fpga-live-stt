"""Linux stdlib-only IPC server for host validation of the native C kernel."""
import ctypes
from pathlib import Path
import struct
import sys
function = ctypes.CDLL(sys.argv[1]).qn_depthwise_f32
pointer = ctypes.POINTER(ctypes.c_float)
function.argtypes = [pointer]*4+[ctypes.c_size_t]*8+[ctypes.c_uint]
function.restype = ctypes.c_int
def read_exact(size):
    data = bytearray()
    while len(data) < size:
        part = sys.stdin.buffer.read(size-len(data))
        if not part:
            if data:
                raise EOFError('Incomplete bridge request')
            return None
        data.extend(part)
    return data
while True:
    header = read_exact(72)
    if header is None:
        break
    *dims,threads,has_bias = struct.unpack('<8QII',header)
    n,c,t,k,stride,dilation,left,right = dims
    out = (t+left+right-dilation*(k-1)-1)//stride+1
    sizes = [n*c*t,c*k,c if has_bias else 0]
    arrays = []
    for size in sizes:
        arrays.append((ctypes.c_float*size).from_buffer_copy(read_exact(size*4)) if size else None)
    y = (ctypes.c_float*(n*c*out))()
    status = function(*arrays,y,*dims,threads)
    sys.stdout.buffer.write(struct.pack('<i',status))
    if status == 0:
        sys.stdout.buffer.write(bytes(y))
    sys.stdout.buffer.flush()
