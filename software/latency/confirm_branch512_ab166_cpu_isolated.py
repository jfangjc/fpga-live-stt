"""Check the selected pure-CPU policies without a resident FPGA session."""
import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path
import numpy as np
import onnx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'software/fused'))
sys.path.insert(0, str(ROOT/'software/model-tools'))
from common import Frontend, read_audio, decode, sha, write_json, environment
from boundary_lut import transform as boundary
from residual_tail import transform as tails
from se_pool import transform as pool
from chain_benchmark import make_session

ap = argparse.ArgumentParser()
ap.add_argument('--runs', type=int, default=100)
ap.add_argument('--out', type=Path, required=True)
a = ap.parse_args()
assert a.runs >= 100
screen_path = ROOT/'reports/fused/branch512_ab166_cpu_policy_wide.json'
screen = json.loads(screen_path.read_text())
assert screen['complete'] and screen['candidate_count'] == 64 and screen['all_warm_logits_bit_exact']
model_path = ROOT/'research/fused/cpu-int8-cse.onnx'
assert sha(model_path) == screen['model_sha256']
libraries = {'boundary': ROOT/'software/latency/libboundary_lut.so',
             'pool': ROOT/'software/latency/libse_pool.so',
             'original': ROOT/'software/latency/libresidual_tail.so',
             'maskfast': ROOT/'software/latency/libresidual_tail_maskfast.so'}
for key, name in [('boundary', 'boundary_library_sha256'), ('pool', 'se_pool_library_sha256'),
                  ('original', 'residual_tail_library_sha256'), ('maskfast', 'maskfast_library_sha256')]:
    assert sha(libraries[key]) == screen[name]
original = onnx.load(model_path)
tail_graph, _ = tails(boundary(original)[0])
pool_graph, _ = pool(tail_graph)
directory = ROOT/'research/export/citrinet-256-ls'
frontend = Frontend(directory)
vocab = (directory/'vocab.txt').read_text().splitlines()
audio_path = ROOT/'research/eval/user-recording/speech.wav'
audio = read_audio(audio_path)
affinity = os.sched_getaffinity(0)
before = environment()
contexts = []
try:
    os.sched_setaffinity(0, {3})
    for context in screen['contexts']:
        seconds = context['context_seconds']
        policy = context['selected']['policy']
        clip = np.ascontiguousarray(audio[:round(seconds*16000)])
        x, n = frontend(clip)
        reference = make_session(original, policy)
        expected, expected_length = reference.run(None, {'features': np.ascontiguousarray(x[:, :, :int(n[0])]), 'feature_lengths': n})
        del reference
        gc.collect()
        selected_libraries = [libraries['boundary'], libraries[policy['tail_impl']]]
        if policy['graph'] == 'pool': selected_libraries.append(libraries['pool'])
        runner = make_session(pool_graph if policy['graph'] == 'pool' else tail_graph, policy, selected_libraries)
        expected_text = decode(expected[0], expected_length[0], vocab)
        rows = []
        for i in range(10+a.runs):
            time.sleep(.003)
            start = time.perf_counter()
            x, n = frontend(clip)
            logits, length = runner.run(None, {'features': np.ascontiguousarray(x[:, :, :int(n[0])]), 'feature_lengths': n})
            text = decode(logits[0], length[0], vocab)
            elapsed = time.perf_counter()-start
            np.testing.assert_array_equal(logits, expected)
            np.testing.assert_array_equal(length, expected_length)
            assert text == expected_text and int(n[0]) == int(seconds*100)+1
            if i >= 10: rows.append(elapsed)
        row = {'context_seconds': seconds, 'cpu_policy': policy, 'cpu_p50': float(np.median(rows)),
               'cpu_p95': float(np.percentile(rows, 95)), 'seconds': rows, 'all_warm_logits_bit_exact': True}
        contexts.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != 'seconds'}), flush=True)
        del runner
        gc.collect()
finally:
    os.sched_setaffinity(0, affinity)
write_json(a.out, {'complete': True, 'hardware_execution': False, 'fpga_session_loaded': False,
                  'scope': 'Independent selected-policy pure-CPU full audio path; no FPGA custom library loaded',
                  'runs_per_context': a.runs, 'contexts': contexts, 'cpu_policy_screen_sha256': sha(screen_path),
                  'cpu_model_sha256': sha(model_path), 'audio_sha256': sha(audio_path), 'source_sha256': sha(__file__),
                  'libraries_sha256': {k: sha(p) for k, p in libraries.items()},
                  'frontend_source_sha256': sha(ROOT/'software/model-tools/citrinet_cpu.py'),
                  'environment_before': before, 'environment_after': environment()})
