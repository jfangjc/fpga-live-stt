"""One resident, evidence-bound CPU or physical FPGA transcription session."""
import argparse
import ctypes
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import threading
import time

import numpy as np
import onnx
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'software/fused'))
from common import Frontend, decode, identity, read_audio, sha


class ResidentTranscriber:
    """Accept mono float32 16-kHz audio already in memory; initialize once.

    A completed paired benchmark binds graph, native library, firmware and
    worker policy. Backend selection is explicit. Hardware errors propagate.
    Outputs on prefixes remain provisional with this noncausal checkpoint.
    """
    def __init__(self, benchmark, backend='fpga'):
        started = time.perf_counter()
        if backend not in ('cpu', 'fpga'):
            raise ValueError('backend must be cpu or fpga')
        self.backend = backend
        self.lock = threading.Lock()
        benchmark = Path(benchmark).resolve()
        proof = json.loads(benchmark.read_text())
        if proof.get('frontend_variant', 'original') != 'original':
            raise ValueError('This interface requires the pinned original frontend')
        self.padding_policy = proof.get('feature_padding_policy', 'original')
        if self.padding_policy not in ('original', 'trim_to_valid'):
            raise ValueError('Unsupported feature padding policy')
        if not proof.get('complete') or not proof.get('hardware_execution'):
            raise ValueError('A completed physical paired latency benchmark is required')
        if not all(r['physical_oracle_bit_parity'] for r in proof['contexts']):
            raise ValueError('Missing exact physical/oracle parity')
        relative_model = proof.get('cpu_model_relative_path', 'research/fused/cpu-int8.onnx')
        if relative_model not in ('research/fused/cpu-int8.onnx', 'research/fused/cpu-int8-cse.onnx'):
            raise ValueError('Unsupported CPU model binding')
        model = ROOT / relative_model
        cpu_proof = json.loads(model.with_suffix('.json').read_text())
        directory = ROOT / 'research/export/citrinet-256-ls'
        if sha(model) != proof['cpu_model_sha256'] or sha(model) != cpu_proof['model_sha256']:
            raise ValueError('CPU model identity mismatch')
        if identity(directory) != cpu_proof['source_identity']:
            raise ValueError('Frontend/checkpoint/decoder identity mismatch')
        if model.name == 'cpu-int8-cse.onnx':
            validation_path = ROOT / 'reports/fused/cse_arm_validation.json'
            validation = json.loads(validation_path.read_text())
            physical_path = (ROOT / proof.get('physical_validation_relative_path',
                                             'reports/fused/cse_physical_validation.json')).resolve()
            physical_path.relative_to((ROOT / 'reports/fused').resolve())
            physical = json.loads(physical_path.read_text())
            if 'physical_validation_sha256' in proof and sha(physical_path) != proof['physical_validation_sha256']:
                raise ValueError('Physical validation report identity mismatch')
            if (sha(validation_path) != proof['numerical_validation_sha256'] or
                not validation.get('complete') or not validation.get('all_logits_bit_exact') or
                validation['cse_model_sha256'] != sha(model) or
                cpu_proof['parent_model_sha256'] != sha(ROOT / 'research/fused/cpu-int8.onnx') or
                cpu_proof['transform_source_sha256'] != sha(Path(__file__).with_name('eliminate_duplicates.py')) or
                cpu_proof['shape_proof_source_sha256'] != sha(Path(__file__).with_name('share_shape_metadata.py'))):
                raise ValueError('Optimized graph numerical/source binding mismatch')
            if (not physical.get('complete') or not physical.get('hardware_execution') or
                physical['cpu_model_sha256'] != sha(model) or physical['nodes'] != proof['nodes'] or
                physical['library_sha256'] != proof['library_sha256'] or
                physical['firmware_sha256'] != proof['firmware_sha256'] or
                physical['wer_degradation_percentage_points'] > 1 or
                not all(r['physical_oracle_bit_parity'] for r in physical['clips'])):
                raise ValueError('Optimized graph physical accuracy binding mismatch')
            if self.padding_policy == 'trim_to_valid':
                if (physical.get('feature_padding_policy') != 'trim_to_valid' or
                    'physical_validation_sha256' not in proof or
                    not all(r['within_tolerance'] and r['original_trimmed_cpu_text_exact'] and
                            r['length_exact'] for r in physical['clips'])):
                    raise ValueError('Trimmed feature padding lacks bound numerical validation')
        elif self.padding_policy != 'original':
            raise ValueError('Trimmed padding requires the validated CSE model')
        self.nodes = proof['nodes']
        self.main_core = proof.get('main_core')
        workers = proof.get('worker_cores')
        if self.main_core is not None:
            expected_workers = [v for v in range(4) if v != self.main_core][:proof['cpu_threads']-1]
            if self.main_core not in (0,3) or workers != expected_workers:
                raise ValueError('Unsupported measured CPU affinity binding')
        self.lib = None
        opt = ort.SessionOptions()
        opt.intra_op_num_threads = proof['cpu_threads']
        opt.inter_op_num_threads = 1
        opt.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        spin = proof.get('spin_duration_us', 0)
        opt.add_session_config_entry('session.intra_op.allow_spinning', '1' if spin else '0')
        opt.add_session_config_entry('session.inter_op.allow_spinning', '0')
        opt.add_session_config_entry('session.intra_op.spin_duration_us', str(spin))
        opt.add_session_config_entry('session.intra_op.spin_backoff_max', str(proof.get('spin_backoff_max', 8)))
        if self.main_core is not None and workers:
            opt.add_session_config_entry('session.intra_op_thread_affinities', ';'.join(str(v+1) for v in workers))
        graph_path = model
        if backend == 'fpga':
            if proof['runtime'] != 'bulk':
                raise ValueError('This deployment supports the verified bulk image only')
            graph_path = benchmark.with_suffix('.onnx')
            runtime = ROOT / 'software/ort_fpga_bulk'
            library = runtime / 'libort_fpga.so'
            firmware = Path('/lib/firmware/xilinx/asr-v3-bulk/asr-v3-bulk.bit.bin')
            clock = Path('/sys/bus/platform/devices/asr-v3-bulk-clock/set_rate')
            if sha(graph_path) != proof['fpga_graph_sha256'] or sha(library) != proof['library_sha256']:
                raise ValueError('Physical graph/native operator identity mismatch')
            if sha(firmware) != proof['firmware_sha256'] or int(clock.read_text()) != proof['pl_clock_hz']:
                raise ValueError('Physical firmware/clock identity mismatch')
            sys.path.insert(0, str(runtime))
            from probe import stats
            self.stats = stats
            self.lib = ctypes.CDLL(str(library.resolve()))
            opt.register_custom_ops_library(str(library.resolve()))
        graph = onnx.shape_inference.infer_shapes(onnx.load(str(graph_path)))
        with self._placement():
            self.runner = ort.InferenceSession(graph.SerializeToString(), opt, providers=['CPUExecutionProvider'])
        self.frontend = Frontend(directory)
        self.vocab = (directory / 'vocab.txt').read_text().splitlines()
        self.initialization_seconds = time.perf_counter() - started
        self.policy = {'threads': proof['cpu_threads'], 'spin_duration_us': spin,
                       'main_core': self.main_core, 'worker_cores': workers,
                       'feature_padding_policy': self.padding_policy}

    @contextmanager
    def _placement(self):
        if self.main_core is None:
            yield
            return
        previous = os.sched_getaffinity(0)
        try:
            os.sched_setaffinity(0, {self.main_core})
            yield
        finally:
            os.sched_setaffinity(0, previous)

    def transcribe(self, audio):
        audio = np.asarray(audio)
        if audio.dtype != np.float32 or audio.ndim != 1 or len(audio) < 320 or not np.all(np.isfinite(audio)):
            raise ValueError('Expected finite mono float32 audio at 16 kHz, at least 20 ms')
        audio = np.ascontiguousarray(audio)
        with self.lock, self._placement():
            before = self.stats(self.lib) if self.lib else None
            start = time.perf_counter()
            features, lengths = self.frontend(audio)
            if self.padding_policy == 'trim_to_valid':
                features = np.ascontiguousarray(features[:,:,:int(lengths[0])])
            front = time.perf_counter()
            logits, encoded = self.runner.run(None, {'features': features, 'feature_lengths': lengths})
            model = time.perf_counter()
            text = decode(logits[0], encoded[0], self.vocab)
            end = time.perf_counter()
            counters = {k: v - before[k] for k, v in self.stats(self.lib).items()} if self.lib else None
            if counters and (counters['physical_calls'] != len(self.nodes) or counters['oracle_calls']):
                raise RuntimeError('Expected physical execution did not occur')
            if not np.all(np.isfinite(logits)):
                raise RuntimeError('Nonfinite model output')
            return {'text': text, 'backend': self.backend, 'seconds': end - start,
                    'frontend_seconds': front - start, 'model_seconds': model - front,
                    'decode_seconds': end - model, 'audio_seconds': len(audio) / 16000,
                    'encoded_length': int(encoded[0]), 'fpga_counters': counters,
                    'worker_policy': self.policy, 'prefix_text_is_provisional': True}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--benchmark', type=Path, required=True)
    ap.add_argument('--backend', choices=('cpu', 'fpga'), default='fpga')
    ap.add_argument('--wav', type=Path, nargs='+', required=True)
    ap.add_argument('--prefix-seconds', type=float)
    ap.add_argument('--warmups', type=int, default=3)
    ap.add_argument('--repeats', type=int, default=1)
    args = ap.parse_args()
    if args.warmups < 0 or args.repeats < 1:
        ap.error('warmups must be nonnegative; repeats must be positive')
    runner = ResidentTranscriber(args.benchmark, args.backend)
    print(json.dumps({'initialization_seconds': runner.initialization_seconds, 'worker_policy': runner.policy}), flush=True)
    for path in args.wav:
        audio = read_audio(path)
        if args.prefix_seconds is not None:
            if args.prefix_seconds < .02 or args.prefix_seconds > len(audio) / 16000:
                ap.error('prefix must fit the audio and be at least 20 ms')
            audio = audio[:round(args.prefix_seconds * 16000)]
        for _ in range(args.warmups):
            runner.transcribe(audio)
        for i in range(args.repeats):
            print(json.dumps(dict(runner.transcribe(audio), wav=str(path), repeat=i)), flush=True)


if __name__ == '__main__':
    main()
