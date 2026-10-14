"""Profile accepted trimmed INT8 model and expose quantized convolution topology.

Instrumentation is diagnostic only; these durations are not acceptance timing.
"""
import argparse
import collections
import json
import os
from pathlib import Path
import re
import sys
import time
import numpy as np
import onnx
from onnx import helper, numpy_helper
import onnxruntime as ort
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'software/fused'))
from common import Frontend, read_audio, sha, identity, environment, write_json


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seconds', type=float, default=.5)
    ap.add_argument('--runs', type=int, default=20)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    model_path = ROOT / 'research/fused/cpu-int8-cse.onnx'
    proof = json.loads(model_path.with_suffix('.json').read_text())
    directory = ROOT / 'research/export/citrinet-256-ls'
    assert sha(model_path) == proof['model_sha256']
    assert identity(directory) == proof['source_identity']
    graph = onnx.load(str(model_path))
    arrays = {v.name: numpy_helper.to_array(v) for v in graph.graph.initializer}
    producers = {o: n for n in graph.graph.node for o in n.output}
    consumers = collections.defaultdict(list)
    for n in graph.graph.node:
        for i in n.input: consumers[i].append(n)
    audio_path = ROOT / 'research/eval/user-recording/speech.wav'
    audio = read_audio(audio_path)
    assert .02 <= a.seconds <= len(audio)/16000 and a.runs >= 3
    x, length = Frontend(directory)(audio[:round(a.seconds*16000)])
    x = np.ascontiguousarray(x[:, :, :int(length[0])])
    opt = ort.SessionOptions()
    opt.intra_op_num_threads = 4; opt.inter_op_num_threads = 1
    opt.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    spin = 10 if a.seconds >= 1 else 0
    opt.add_session_config_entry('session.intra_op.allow_spinning', '1' if spin else '0')
    opt.add_session_config_entry('session.inter_op.allow_spinning', '0')
    opt.add_session_config_entry('session.intra_op.spin_duration_us', str(spin))
    opt.add_session_config_entry('session.intra_op.spin_backoff_max', '8')
    opt.add_session_config_entry('session.intra_op_thread_affinities', '1;2;3')
    opt.enable_profiling = True
    a.out.parent.mkdir(parents=True, exist_ok=True)
    opt.profile_file_prefix = str(a.out.with_suffix(''))
    previous = os.sched_getaffinity(0)
    try:
        os.sched_setaffinity(0, {3})
        runner = ort.InferenceSession(graph.SerializeToString(), opt, providers=['CPUExecutionProvider'])
        feed = {'features': x, 'feature_lengths': length}
        before = environment()
        for _ in range(3): runner.run(None, feed)
        for _ in range(a.runs): runner.run(None, feed)
        trace = Path(runner.end_profiling())
        after = environment()
    finally:
        os.sched_setaffinity(0, previous)
    events = json.loads(trace.read_text())
    intervals = [e for e in events if e.get('name') == 'model_run'][-a.runs:]
    totals = collections.defaultdict(list); metadata = {}
    for e in events:
        if (e.get('cat') == 'Node' and e['name'].endswith('_kernel_time') and
                any(r['ts'] <= e['ts'] < r['ts']+r['dur'] for r in intervals)):
            name = e['name'].removesuffix('_kernel_time')
            totals[name].append(e['dur']); metadata[name] = e.get('args', {})
    nodes = []; blocks = collections.defaultdict(float); operators = collections.defaultdict(float)
    for name, values in totals.items():
        median = float(np.median(values)); operator = metadata[name].get('op_name')
        nodes.append({'name': name, 'operator': operator, 'median_us': median,
                      'input_type_shape': metadata[name].get('input_type_shape'),
                      'output_type_shape': metadata[name].get('output_type_shape')})
        match = re.search(r'/encoder/encoder\.(\d+)/', name)
        blocks[match.group(1) if match else 'other'] += median
        operators[operator] += median
    convs = []
    for n in graph.graph.node:
        if n.op_type != 'QLinearConv': continue
        attrs = {v.name: helper.get_attribute_value(v) for v in n.attribute}
        w = arrays[n.input[3]]
        convs.append({'name': n.name, 'inputs': list(n.input), 'output': n.output[0],
                      'weight_shape': list(w.shape), 'attributes': attrs,
                      'input_producer': producers[n.input[0]].name if n.input[0] in producers else None,
                      'consumers': [{'name': c.name, 'op': c.op_type, 'inputs': list(c.input),
                                     'outputs': list(c.output)} for c in consumers[n.output[0]]],
                      'median_us': float(np.median([d for key, values in totals.items()
                                                     if key == n.name or key.startswith(n.name+'_token_')
                                                     for d in values] or [0]))})
    report = {'complete': True, 'scope': 'Instrumented diagnostics; no FPGA or latency acceptance',
              'model_sha256': sha(model_path), 'source_sha256': sha(Path(__file__)),
              'audio_sha256': sha(audio_path), 'context_seconds': a.seconds, 'runs': a.runs,
              'feature_shape': list(x.shape), 'policy': {'threads': 4, 'main_core': 3, 'spin_us': spin},
              'environment_before': before, 'environment_after': after,
              'trace': str(trace), 'trace_sha256': sha(trace),
              'blocks': sorted(blocks.items(), key=lambda p:p[1], reverse=True),
              'operators': sorted(operators.items(), key=lambda p:p[1], reverse=True),
              'nodes': sorted(nodes, key=lambda p:p['median_us'], reverse=True),
              'convolutions': convs}
    write_json(a.out, report)
    print(json.dumps({'blocks': report['blocks'][:8], 'operators': report['operators'],
                      'nodes': report['nodes'][:8]}, indent=2), flush=True)


if __name__ == '__main__': main()
