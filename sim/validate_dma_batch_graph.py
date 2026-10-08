"""Compare whole-model batch packet execution with INT32 matmul emulation."""
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root/'software'), str(root/'software/asr-baseline')]
from batch_smoke import EmulatedBatch
from quartznet_hybrid import Graph, vocabulary
from quartznet_cpu import read_pcm24, frontend, decode

audio = read_pcm24(Path('C:/Users/jfang/Downloads/speech.wav'))
audio -= audio.mean()
features, valid = frontend(audio)
features = features[:, :, :valid].copy()
model = root/'software/asr-baseline/model'
hashes = {}
def remember(node, result):
    hashes[node.name] = hashlib.sha256(result.tobytes()).hexdigest()
def compare(node, result):
    assert hashlib.sha256(result.tobytes()).hexdigest() == hashes[node.name], node.name

reference = Graph(model/'model.onnx', mode='emulate')
started = time.perf_counter()
expected = reference.run(features, observer=remember)
reference_seconds = time.perf_counter()-started
transport = EmulatedBatch(batch_size=64)
transport.accepts_buffer = True
batched = Graph(model/'model.onnx', mode='dma', transact=transport)
started = time.perf_counter()
actual = batched.run(features, observer=compare)
batch_seconds = time.perf_counter()-started
np.testing.assert_array_equal(actual, expected)
result = {
    'result':'PASS', 'hardware_execution':False, 'all_node_outputs_bit_exact':True,
    'nodes_checked':len(hashes), 'batch_size':64,
    'tile_packets':transport.tile_packets, 'batch_calls':transport.ioctl_calls,
    'input_bytes':transport.input_bytes_sent,
    'reference_emulation_seconds':reference_seconds,
    'batch_emulation_seconds':batch_seconds,
    'transcript':decode(actual, vocabulary(model), (valid+1)//2),
    'note':'Host emulation correctness test; not a board throughput or WER measurement'
}
(root/'reports/quartznet_batch_graph_host.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
