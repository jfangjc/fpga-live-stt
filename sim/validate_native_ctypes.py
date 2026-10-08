"""Linux portable-C tests using fixtures; no NumPy dependency in WSL."""
import ctypes
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
directory = root/'reports/native-fixtures'
library = ctypes.CDLL(sys.argv[1])
pointer = ctypes.POINTER(ctypes.c_float)
function = library.qn_depthwise_f32
function.argtypes = [pointer]*4+[ctypes.c_size_t]*8+[ctypes.c_uint]
function.restype = ctypes.c_int
checks = 0
max_error = 0.
for fixture in json.loads((directory/'manifest.json').read_text()):
    n,c,t,k,stride,dilation,left,right = fixture['dims']
    out_t = fixture['output_shape'][2]
    sizes = [n*c*t,c*k,c,n*c*out_t]
    data = (directory/fixture['file']).read_bytes()
    arrays = []
    offset = 0
    for size in sizes:
        arrays.append((ctypes.c_float*size).from_buffer_copy(data[offset:offset+4*size]))
        offset += size*4
    assert offset == len(data)
    x,w,bias,expected = arrays
    for threads in (1,4):
        actual = (ctypes.c_float*(n*c*out_t))()
        status = function(x,w,bias if fixture['bias'] else None,actual,*fixture['dims'],threads)
        assert status == 0, (fixture['node'],status)
        scale = max(1.,max(abs(v) for v in expected))
        error = max(abs(a-b) for a,b in zip(actual,expected))/scale
        assert error <= 5e-6,(fixture['node'],error)
        max_error = max(max_error,error)
        checks += 1
report = {'result':'PASS','fpga_execution':False,'arm_execution':False,
          'model_fixture_checks':checks,'max_scaled_error':max_error,
          'note':'Portable C branch on Linux x86, model-derived same-input comparisons. ARM NEON and full ASR require board validation.'}
(root/'reports/native_ctypes_host.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
