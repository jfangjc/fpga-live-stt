"""Compare dynamic and fixed-frame CPU/physical FPGA graphs fairly."""
import argparse
import copy
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
from onnx import numpy_helper
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'software/ort_fpga_bulk'))
from probe import candidate, stats
from common import Frontend, read_audio, decode, sha, identity, environment, write_json


def fixed(model, frames, valid=None):
    graph = copy.deepcopy(model)
    expected = {'features': [1, 80, frames], 'feature_lengths': [1]}
    assert {v.name for v in graph.graph.input} == set(expected)
    for v in graph.graph.input:
        assert len(v.type.tensor_type.shape.dim) == len(expected[v.name])
        for dim, size in zip(v.type.tensor_type.shape.dim, expected[v.name]):
            dim.ClearField('dim_param')
            dim.dim_value = size
    # Discard inferred dynamic metadata; infer it from the declared inputs.
    del graph.graph.value_info[:]
    if valid is not None:
        assert 1 <= valid <= frames
        name = 'short_fixed_valid_length'
        assert name not in {v.name for v in graph.graph.initializer}
        graph.graph.initializer.append(numpy_helper.from_array(np.array([valid],np.int64),name))
        for node in graph.graph.node:
            for i, source in enumerate(node.input):
                if source == 'feature_lengths': node.input[i] = name
    onnx.checker.check_model(graph)
    return onnx.shape_inference.infer_shapes(graph)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--nodes', nargs='+', required=True)
    ap.add_argument('--contexts', nargs='+', type=float, default=[.5, 1])
    ap.add_argument('--runs', type=int, default=50)
    ap.add_argument('--freeze-length', action='store_true', help='Specialize exact valid length; caller must enforce it')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    a.out = a.out.resolve()
    assert a.runs >= 30 and sorted(os.sched_getaffinity(0)) == [0,1,2,3]
    os.sched_setaffinity(0, {3})
    model_path = ROOT / 'research/fused/cpu-int8-cse.onnx'
    validation = ROOT / 'reports/fused/cse_arm_validation.json'
    proof = json.loads(model_path.with_suffix('.json').read_text())
    numerical = json.loads(validation.read_text())
    assert numerical['complete'] and numerical['all_logits_bit_exact']
    assert sha(model_path) == proof['model_sha256'] == numerical['cse_model_sha256']
    directory = ROOT / 'research/export/citrinet-256-ls'
    assert identity(directory) == proof['source_identity']
    library = ROOT / 'software/ort_fpga_bulk/libort_fpga.so'
    lib = ctypes.CDLL(str(library.resolve()))
    firmware = Path('/lib/firmware/xilinx/asr-v3-bulk/asr-v3-bulk.bit.bin')
    clock = Path('/sys/bus/platform/devices/asr-v3-bulk-clock/set_rate')
    assert 99000000 <= int(clock.read_text()) <= 101000000
    model = onnx.load(str(model_path))
    def session(graph, native=False):
        opt = ort.SessionOptions()
        opt.intra_op_num_threads = 4; opt.inter_op_num_threads = 1
        opt.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opt.add_session_config_entry('session.intra_op.allow_spinning','0')
        opt.add_session_config_entry('session.inter_op.allow_spinning','0')
        opt.add_session_config_entry('session.intra_op_thread_affinities','1;2;3')
        if native: opt.register_custom_ops_library(str(library.resolve()))
        return ort.InferenceSession(onnx.shape_inference.infer_shapes(graph).SerializeToString(),opt,providers=['CPUExecutionProvider'])
    frontend = Frontend(directory)
    vocab = (directory / 'vocab.txt').read_text().splitlines()
    full = read_audio(ROOT / 'research/eval/user-recording/speech.wav')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(111026); summary = []; rows = []
    for seconds in sorted(set(a.contexts)):
        assert .02 <= seconds <= len(full)/16000
        audio = np.ascontiguousarray(full[:round(seconds*16000)])
        x,n = frontend(audio); frames = x.shape[-1]
        static = fixed(model, frames, int(n[0]) if a.freeze_length else None)
        graphs = {'dynamic_cpu': model, 'dynamic_fpga': candidate(model,a.nodes,quant=True),
                  'cpu': static, 'fpga': candidate(static,a.nodes,quant=True)}
        runners = {}; setup = {}
        for name,g in graphs.items():
            start = time.perf_counter(); runners[name] = session(g, name.endswith('fpga'))
            setup[name] = time.perf_counter()-start
        oracle = session(candidate(static,a.nodes,oracle=True,quant=True), True)
        # Check distinct valid lengths in this bucket, not just the timed clip.
        checks = []
        for valid in ([int(n[0])] if a.freeze_length else sorted(set([1, frames//2, frames-1, int(n[0])]))):
            feed = {'features': x, 'feature_lengths': np.array([valid],np.int64)}
            outputs = {name:r.run(None,feed) for name,r in runners.items()}
            for old,new in [('dynamic_cpu','cpu'),('dynamic_fpga','fpga')]:
                for left,right in zip(outputs[old],outputs[new]): np.testing.assert_array_equal(left,right)
            for left,right in zip(oracle.run(None,feed),outputs['fpga']): np.testing.assert_array_equal(left,right)
            checks.append({'valid_length':valid,'cpu_bit_exact':True,'fpga_bit_exact':True,'physical_oracle_bit_parity':True})
        graph_path = a.out.with_name(a.out.stem+f'_frames{frames}.onnx')
        onnx.save(graphs['fpga'],str(graph_path))
        def call(name):
            time.sleep(.003)
            before = stats(lib); start = time.perf_counter()
            features,lengths = frontend(audio); front = time.perf_counter()
            assert features.shape == (1,80,frames)
            if a.freeze_length: assert np.array_equal(lengths,n), 'Specialized valid-length contract violated'
            y,encoded = runners[name].run(None,{'features':features,'feature_lengths':lengths})
            inference = time.perf_counter(); text = decode(y[0],encoded[0],vocab); end = time.perf_counter()
            delta = {k:v-before[k] for k,v in stats(lib).items()}
            assert delta['physical_calls'] == (len(a.nodes) if name.endswith('fpga') else 0)
            assert delta['oracle_calls'] == 0 and np.all(np.isfinite(y))
            return {'seconds':end-start,'frontend_seconds':front-start,'model_seconds':inference-front,
                    'decode_seconds':end-inference,'text':text,'encoded_length':int(encoded[0]),'fpga_counters':delta}
        for _ in range(3):
            for name in runners: call(name)
        pairs = []; before_env = environment()
        for i in range(a.runs):
            order = list(runners); rng.shuffle(order)
            pair = {name:call(name) for name in order}
            assert pair['cpu']['text'] == pair['dynamic_cpu']['text']
            assert pair['fpga']['text'] == pair['dynamic_fpga']['text']
            pairs.append(pair); rows.append({'context_seconds':seconds,'repeat':i,'order':order,'results':pair})
        values = {name:np.array([r[name]['seconds'] for r in pairs]) for name in runners}
        indices = np.random.default_rng(111026).integers(0,a.runs,(10000,a.runs))
        def ci(old,new):return np.percentile((values[old]-values[new])[indices].mean(1),[2.5,97.5]).tolist()
        result = {'context_seconds':seconds,'feature_frames':frames,'valid_length':int(n[0]) if a.freeze_length else None,
                  'shape_validation':checks,'initialization_seconds':setup,
                  'environment_before':before_env,'environment_after':environment(),
                  'mean_saving_95ci_seconds':ci('cpu','fpga'),
                  'static_cpu_saving_95ci_seconds':ci('dynamic_cpu','cpu'),
                  'static_fpga_saving_95ci_seconds':ci('dynamic_fpga','fpga'),
                  'fpga_graph_relative_path':graph_path.relative_to(ROOT).as_posix(),'fpga_graph_sha256':sha(graph_path)}
        for name,v in values.items():
            result[name+'_p50'] = float(np.median(v)); result[name+'_p95'] = float(np.percentile(v,95))
        summary.append(result)
        write_json(a.out, {'complete':len(summary)==len(set(a.contexts)),'hardware_execution':True,
                   'scope':'Fixed-shape screening; frontend/graph/decoder timed; initialization separate',
                   'runs':a.runs,'nodes':a.nodes,'freeze_length':a.freeze_length,'cpu_threads':4,'main_core':3,'worker_cores':[0,1,2],
                   'spin_duration_us':0,'idle_between_calls_seconds':.003,'model_sha256':sha(model_path),
                   'numerical_validation_sha256':sha(validation),'library_sha256':sha(library),
                   'firmware_sha256':sha(firmware),'pl_clock_hz':int(clock.read_text()),'source_sha256':sha(__file__),
                   'contexts':summary,'paired_runs':rows,'capture_tested':False})
        print(seconds,{name:round(result[name+'_p50']*1000,3) for name in runners},'CI',result['mean_saving_95ci_seconds'],flush=True)
        del runners, oracle


if __name__ == '__main__':
    main()
