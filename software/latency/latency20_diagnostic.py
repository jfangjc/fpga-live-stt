"""Fresh baseline/profile after a kernel change; never an acceptance result."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import random
import sys
import time
import numpy as np
import onnx
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'software/fused'))
sys.path.insert(0, str(ROOT / 'software/ort_fpga_bulk'))
sys.path.insert(0, str(ROOT / 'software/ort_fpga_shortwide'))
sys.path.insert(0, str(ROOT / 'software/latency'))
from common import Frontend, decode, environment, read_audio, sha, write_json
from graph import candidate
from probe import stats
from dma_irq import configure, snapshot


def make_session(graph, library=None, spin=0, profile=None):
    opt = ort.SessionOptions()
    opt.intra_op_num_threads = 4
    opt.inter_op_num_threads = 1
    opt.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    for key, value in [('session.intra_op.allow_spinning', '1' if spin else '0'),
                       ('session.inter_op.allow_spinning', '0'),
                       ('session.intra_op.spin_duration_us', str(spin)),
                       ('session.intra_op.spin_backoff_max', '8'),
                       ('session.intra_op_thread_affinities', '1;2;3')]:
        opt.add_session_config_entry(key, value)
    if library:
        opt.register_custom_ops_library(str(library))
    if profile:
        opt.enable_profiling = True
        opt.profile_file_prefix = str(profile)
    return ort.InferenceSession(onnx.shape_inference.infer_shapes(graph).SerializeToString(), opt,
                               providers=['CPUExecutionProvider'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', type=int, default=30)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    model_path = ROOT / 'research/fused/cpu-int8-cse.onnx'
    model = onnx.load(model_path)
    library = ROOT / 'software/ort_fpga_shortwide/libort_fpga.so'
    lib = ctypes.CDLL(str(library))
    graph = candidate(model)
    front = Frontend(ROOT / 'research/export/citrinet-256-ls')
    vocab = (ROOT / 'research/export/citrinet-256-ls/vocab.txt').read_text().splitlines()
    audio = read_audio(ROOT / 'research/eval/user-recording/speech.wav')
    affinity = os.sched_getaffinity(0)
    irq_before = snapshot()
    result = {'complete': False, 'timing_acceptance': False, 'hardware_execution': True,
              'source_sha256': sha(__file__), 'cpu_model_sha256': sha(model_path),
              'library_sha256': sha(library), 'environment_before': environment(), 'contexts': []}
    try:
        os.sched_setaffinity(0, {3})
        for seconds in (.5, 1, 2.5):
            configure(0 if seconds == .5 else 3)
            runners = {'cpu': make_session(model, spin=10),
                       'fpga': make_session(graph, library, 10 if seconds == .5 else 0),
                       'oracle': make_session(candidate(model, True), library)}
            clip = np.ascontiguousarray(audio[:round(seconds * 16000)])
            rows = []
            def call(kind):
                before = stats(lib)
                start = time.perf_counter()
                x, n = front(clip)
                x = np.ascontiguousarray(x[:, :, :int(n[0])])
                middle = time.perf_counter()
                logits, length = runners[kind].run(None, {'features': x, 'feature_lengths': n})
                end_model = time.perf_counter()
                text = decode(logits[0], length[0], vocab)
                end = time.perf_counter()
                delta = {k: v - before[k] for k, v in stats(lib).items()}
                return {'seconds': end-start, 'frontend_seconds': middle-start,
                        'model_seconds': end_model-middle, 'decode_seconds': end-end_model,
                        'text': text, 'length': int(length[0]), 'counters': delta}, logits
            physical, actual = call('fpga')
            oracle, expected = call('oracle')
            np.testing.assert_array_equal(actual, expected)
            cpu, _ = call('cpu')
            assert cpu['text'] == physical['text'] and cpu['length'] == physical['length']
            for _ in range(3):
                call('cpu'); call('fpga')
            rng = random.Random(20261011)
            for i in range(a.runs):
                order = ['cpu', 'fpga']; rng.shuffle(order)
                row = {'index': i, 'order': order, 'results': {}}
                for kind in order:
                    time.sleep(.003)
                    row['results'][kind], _ = call(kind)
                assert row['results']['fpga']['counters']['loads'] == 0
                assert row['results']['fpga']['counters']['ioctls'] == 32
                rows.append(row)
            summary = {'context_seconds': seconds, 'physical_oracle_bit_parity': True,
                       'runs': rows}
            for kind in ('cpu', 'fpga'):
                samples = [r['results'][kind]['seconds'] for r in rows]
                summary[kind+'_p50'] = float(np.median(samples))
                summary[kind+'_p95'] = float(np.percentile(samples, 95))
            summary['reduction_percent'] = 100*(1-summary['fpga_p50']/summary['cpu_p50'])
            result['contexts'].append(summary)
            print(json.dumps({k: v for k,v in summary.items() if k!='runs'}), flush=True)
            del runners
        configure(3)
        x, n = front(audio[:16000]); x = np.ascontiguousarray(x[:, :, :int(n[0])])
        runner = make_session(graph, library, profile=a.out.with_suffix('.profile'))
        for _ in range(8):
            runner.run(None, {'features': x, 'feature_lengths': n})
        trace = Path(runner.end_profiling())
        result['profile_path'] = str(trace)
        result['profile_sha256'] = sha(trace)
        result['complete'] = True
        result['environment_after'] = environment()
        write_json(a.out, result)
    finally:
        os.sched_setaffinity(0, affinity)
        for irq, value in irq_before.items():
            (Path('/proc/irq') / irq / 'smp_affinity_list').write_text(value['requested'])


if __name__ == '__main__':
    main()
