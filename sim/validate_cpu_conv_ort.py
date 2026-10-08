"""Isolate Conv numerical changes, then compare complete quantized graphs."""
import json
from pathlib import Path
import sys
import time
import numpy as np

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root/'software'),str(root/'software/asr-baseline')]
from quartznet_hybrid import Graph, vocabulary
from quartznet_cpu import read_pcm24, frontend, decode
from batch_smoke import EmulatedBatch

audio = read_pcm24(Path('C:/Users/jfang/Downloads/speech.wav'))
audio -= audio.mean()
features, valid = frontend(audio)
features = features[:,:,:valid].copy()
model = root/'software/asr-baseline/model'
reference = Graph(model/'model.onnx',mode='emulate')
transport = EmulatedBatch(128)
transport.accepts_buffer = True
accelerated = Graph(model/'model.onnx',mode='dma',transact=transport,cpu_conv_backend='ort')
assert len(accelerated.quantized) == 94
assert len(accelerated.cpu_sessions) == 77
assert not set(accelerated.quantized).intersection(accelerated.cpu_sessions)
ordinary = reference.convolution
checks = []
def checked(node,x):
    expected = ordinary(node,x)
    if node.name in accelerated.cpu_sessions:
        actual = accelerated.convolution(node,x)
        error = float(np.max(np.abs(expected-actual)))
        scale = max(1.,float(np.max(np.abs(expected))))
        assert actual.shape == expected.shape
        assert error <= 2e-5*scale, (node.name,error,scale)
        checks.append(error/scale)
    return expected
reference.convolution = checked
cases = []
for length in (100,251,valid):
    x = features[:,:,:length].copy()
    expected = reference.run(x)
    started = time.perf_counter()
    actual = accelerated.run(x)
    seconds = time.perf_counter()-started
    assert np.all(np.isfinite(actual)) and expected.shape == actual.shape
    frame_agreement = float(np.mean(expected.argmax(-1) == actual.argmax(-1)))
    assert frame_agreement >= .95
    cases.append({'feature_frames':int(length),'host_emulated_dma_seconds':seconds,
                  'frame_argmax_agreement':frame_agreement,
                  'max_final_logprob_difference':float(np.max(np.abs(expected-actual))),
                  'numpy_transcript':decode(expected,vocabulary(model),(length+1)//2),
                  'ort_cpu_transcript':decode(actual,vocabulary(model),(length+1)//2),
                  'other_graph_seconds':sum(n['seconds'] for n in accelerated.stats if not n['int8_pointwise']),
                  'int8_pointwise_nodes':sum(n['int8_pointwise'] for n in accelerated.stats)})
report = {'result':'PASS','hardware_execution':False,
          'isolated_cpu_conv_checks':len(checks),'max_scaled_cpu_conv_error':max(checks),
          'cpu_conv_sessions':77,'pointwise_nodes_preserved':94,'cases':cases,
          'note':'FP32 accumulation order differs; whole quantized graph is not bit exact. No board speed or corpus accuracy validation.'}
(root/'reports/quartznet_cpu_conv_ort_host.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
