"""Write model CPU Conv inputs/NumPy outputs for pure-ctypes Linux tests."""
import json
from pathlib import Path
import sys
import numpy as np

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root/'software'),str(root/'software/asr-baseline')]
from quartznet_hybrid import Graph
from quartznet_cpu import read_pcm24, frontend

directory = root/'reports/native-fixtures'
directory.mkdir(exist_ok=True)
audio = read_pcm24(Path('C:/Users/jfang/Downloads/speech.wav'))
audio -= audio.mean()
features,valid = frontend(audio)
graph = Graph(root/'software/asr-baseline/model/model.onnx',mode='emulate')
ordinary = graph.convolution
fixtures = []
def collect(node,x):
    result = ordinary(node,x)
    if node.name not in graph.quantized:
        w = graph.weights[node.input[1]]
        attrs = graph.attrs[node.name]
        assert w.shape[1] == 1 and attrs.get('group',1) == x.shape[1] == w.shape[0]
        c = min(x.shape[1],7)
        has_bias = len(node.input) > 2
        bias = graph.weights[node.input[2]][:c] if has_bias else np.zeros(c,dtype=np.float32)
        tensors = [x[:,:c],w[:c],bias,result[:,:c]]
        index = len(fixtures)
        dims = [x.shape[0],c,x.shape[2],w.shape[2],attrs.get('strides',[1])[0],
                attrs.get('dilations',[1])[0],*attrs.get('pads',[0,0])]
        filename = f'{index:03}.bin'
        (directory/filename).write_bytes(b''.join(np.ascontiguousarray(a,dtype='<f4').tobytes() for a in tensors))
        fixtures.append({'file':filename,'node':node.name,'dims':dims,
                         'output_shape':[result.shape[0],c,result.shape[2]],'bias':has_bias})
    return result
graph.convolution = collect
for length in (100,251,valid):
    graph.run(features[:,:,:length].copy())
assert len(fixtures) == 231
(directory/'manifest.json').write_text(json.dumps(fixtures,indent=2)+'\n')
print(json.dumps({'fixtures':len(fixtures),'directory':str(directory)}))
