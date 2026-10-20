"""Diagnostic ORT node profiles for one context; not timing acceptance."""
import argparse
import collections
import ctypes
import json
from pathlib import Path
import sys
import time
import numpy as np
import onnx
import onnxruntime as ort
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'software/ort_fpga_bulk'))
from probe import candidate, stats
from common import Frontend, read_audio, sha, identity, write_json

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--nodes', nargs='+', required=True)
    ap.add_argument('--seconds', type=float, default=1)
    ap.add_argument('--runs', type=int, default=10)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    cpu = ROOT / 'research/fused/cpu-int8.onnx'
    model = onnx.load(str(cpu))
    proof = json.loads(cpu.with_suffix('.json').read_text())
    directory = ROOT / 'research/export/citrinet-256-ls'
    assert sha(cpu) == proof['model_sha256'] and identity(directory) == proof['source_identity']
    library = ROOT / 'software/ort_fpga_bulk/libort_fpga.so'
    lib = ctypes.CDLL(str(library.resolve()))
    audio = read_audio(ROOT / 'research/eval/user-recording/speech.wav')
    if a.seconds < .02 or a.seconds > len(audio)/16000 or a.runs < 3:
        raise ValueError('Invalid context or run count')
    x, n = Frontend(directory)(audio[:round(a.seconds*16000)])
    feed = {'features': x, 'feature_lengths': n}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    rows = {}
    for name, graph in [('cpu', model), ('fpga', candidate(model, a.nodes, quant=True))]:
        opt = ort.SessionOptions()
        opt.intra_op_num_threads = 4
        opt.inter_op_num_threads = 1
        opt.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opt.add_session_config_entry('session.intra_op.allow_spinning', '0')
        opt.add_session_config_entry('session.inter_op.allow_spinning', '0')
        opt.enable_profiling = True
        opt.profile_file_prefix = str(a.out.with_suffix('')) + '_' + name
        if name == 'fpga':
            opt.register_custom_ops_library(str(library.resolve()))
        runner = ort.InferenceSession(onnx.shape_inference.infer_shapes(graph).SerializeToString(), opt,
                                      providers=['CPUExecutionProvider'])
        before = stats(lib)
        for _ in range(a.runs):
            logits, length = runner.run(None, feed)
            assert np.all(np.isfinite(logits))
        after = stats(lib)
        delta = {k: after[k]-before[k] for k in after}
        assert delta['physical_calls'] == (len(a.nodes)*a.runs if name == 'fpga' else 0)
        profile = Path(runner.end_profiling())
        totals = collections.defaultdict(list)
        ops = {}
        for e in json.loads(profile.read_text()):
            if e.get('cat') == 'Node' and e['name'].endswith('_kernel_time'):
                totals[e['name']].append(e['dur'])
                ops[e['name']] = e.get('args', {}).get('op_name')
        nodes = [{'node': k, 'operator': ops[k], 'median_us': float(np.median(v[1:] if len(v)>1 else v)),
                  'calls': len(v)} for k,v in totals.items()]
        rows[name] = {'nodes': sorted(nodes, key=lambda v:v['median_us'], reverse=True),
                      'profile': str(profile), 'fpga_counters': delta}
        del runner
        time.sleep(.1)
    write_json(a.out, {'scope': 'Diagnostic profiling with instrumentation; not latency acceptance',
                      'context_seconds': a.seconds, 'runs': a.runs, 'cpu_threads': 4, 'worker_spinning': False,
                      'cpu_model_sha256': sha(cpu), 'library_sha256': sha(library), 'selected_nodes': a.nodes,
                      'source_sha256': sha(Path(__file__)), 'profiles': rows})
    for name, data in rows.items():
        print(name, [(n['operator'], round(n['median_us']), n['node']) for n in data['nodes'][:8]], flush=True)

if __name__ == '__main__':
    main()
