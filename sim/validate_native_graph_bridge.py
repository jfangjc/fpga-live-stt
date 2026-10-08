"""Run native portable-C Conv in WSL within the actual Windows hybrid graph.

IPC is for numerical validation only; elapsed times are not board benchmarks.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import numpy as np

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root/'software'),str(root/'software/asr-baseline')]
parser = argparse.ArgumentParser()
parser.add_argument('--library',required=True)
args = parser.parse_args()
library_wsl = args.library
bridge_wsl = '/mnt/c/Users/jfang/Documents/Vivado/Prototype/sim/native_host_bridge.py'
process = subprocess.Popen(['wsl','-e','python3',bridge_wsl,library_wsl],
                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
def receive(size):
    parts = bytearray()
    while len(parts) < size:
        part = process.stdout.read(size-len(parts))
        if not part:
            raise RuntimeError(process.stderr.read().decode())
        parts.extend(part)
    return parts
class NativeBridge:
    def __init__(self,library=None,threads=4):
        self.threads = threads
        self.calls = 0
        self.sha256 = 'portable-C-WSL-validation-bridge'
    def __call__(self,x,w,bias,attrs):
        n,c,t = x.shape
        k = w.shape[2]
        stride, = attrs.get('strides',[1])
        dilation, = attrs.get('dilations',[1])
        left,right = attrs.get('pads',[0,0])
        out = (t+left+right-dilation*(k-1)-1)//stride+1
        process.stdin.write(struct.pack('<8QII',n,c,t,k,stride,dilation,left,right,self.threads,int(bias is not None)))
        for values in (x,w,bias):
            if values is not None:
                payload = np.ascontiguousarray(values,dtype='<f4').tobytes()
                for offset in range(0,len(payload),16384):
                    process.stdin.write(payload[offset:offset+16384])
        process.stdin.flush()
        status, = struct.unpack('<i',receive(4))
        if status:
            raise RuntimeError(f'Native Conv status {status}')
        self.calls += 1
        return np.frombuffer(receive(n*c*out*4),dtype='<f4').reshape(n,c,out).copy()

import native_depthwise
native_depthwise.NativeDepthwise = NativeBridge
from quartznet_hybrid import Graph,vocabulary
from quartznet_cpu import read_pcm24,frontend,decode
from batch_smoke import EmulatedBatch
model = root/'software/asr-baseline/model'
audio = read_pcm24(Path('C:/Users/jfang/Downloads/speech.wav'))
audio -= audio.mean()
features,valid = frontend(audio)
ordinary = Graph(model/'model.onnx',mode='emulate')
transport = EmulatedBatch(128)
transport.accepts_buffer = True
native = Graph(model/'model.onnx',mode='dma',transact=transport,cpu_conv_backend='native',cpu_conv_threads=4)
assert len(native.native_nodes) == 77 and len(native.quantized) == 94
assert not native.native_nodes.intersection(native.quantized)
cases = []
try:
    for length in (100,251,valid):
        x = features[:,:,:length].copy()
        expected = ordinary.run(x)
        actual = native.run(x)
        assert actual.shape == expected.shape and np.all(np.isfinite(actual))
        agreement = float(np.mean(expected.argmax(-1) == actual.argmax(-1)))
        cases.append({'feature_frames':int(length),'frame_argmax_agreement':agreement,
                      'max_final_logprob_difference':float(np.max(np.abs(expected-actual))),
                      'numpy_transcript':decode(expected,vocabulary(model),(length+1)//2),
                      'native_transcript':decode(actual,vocabulary(model),(length+1)//2),
                      'int8_pointwise_nodes':sum(n['int8_pointwise'] for n in native.stats)})
finally:
    try:
        process.stdin.close()
    except OSError:
        pass
    process.wait(timeout=10)
    if process.returncode:
        print(process.stderr.read().decode(errors='replace'),file=sys.stderr)
report = {'execution':'PASS','whole_graph_bit_exact':False,
          'all_cases_at_least_95_percent_frame_agreement':all(c['frame_argmax_agreement']>=.95 for c in cases),
          'fpga_execution':False,'arm_execution':False,
          'native_cpu_nodes':77,'pointwise_nodes_preserved':94,
          'native_conv_calls':native.native.calls,'cases':cases,
          'note':'Linux x86 portable C through IPC within complete model; ARM NEON and corpus accuracy remain unvalidated. FP32 reduction changes propagate through INT8 rounding.'}
(root/'reports/native_graph_host.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
