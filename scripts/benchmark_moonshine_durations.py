"""Measure streaming CPU/oracle/physical FPGA paths across repeated audio lengths.

Run inside run_moonshine_board.py. Repetition is a timing stress test, not an
independent accuracy corpus. Exit 2 preserves evidence when any timing gate fails.
"""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'software'))


def qualify(case):
    expected = [e['tokens'] for e in case['oracle']['runs'][0]['events']]
    measured = [r for r in case['fpga']['runs'] if r['run'] >= 0]
    parity = all([e['tokens'] for e in r['events']] == expected for r in case['fpga']['runs'])
    truncated = any(r['events'][-1]['token_limit_reached']
                    for backend in ('oracle', 'fpga') for r in case[backend]['runs'])
    physical = bool(measured) and all(r['physical']['runs'] > 0 and r['physical'].get('loads', 0) > 0
                                      for r in measured)
    times = [r['seconds'] for r in measured]
    timing = bool(times) and max(times) < case['audio_seconds']
    return {'oracle_tokens_equal': parity, 'final_token_limit_reached': truncated,
            'physical_execution': physical, 'all_warm_runs_realtime': timing,
            'p50_seconds': statistics.median(times) if times else None,
            'max_seconds': max(times) if times else None,
            'realtime_execution_met': parity and not truncated and physical and timing}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('wav', type=Path)
    p.add_argument('--size', choices=('small', 'tiny'), default='small')
    p.add_argument('--ort-decoder', type=Path, required=True)
    p.add_argument('--chunk-ms', type=int, default=1000)
    p.add_argument('--threads', type=int, default=2)
    p.add_argument('--decoder-threads', type=int, default=4)
    p.add_argument('--ort-encoder', type=Path)
    p.add_argument('--encoder-threads', type=int, default=4)
    p.add_argument('--decoder-scheduling', choices=('sleep', 'run-spin'), default='sleep')
    p.add_argument('--encoder-scheduling', choices=('sleep', 'run-spin'), default='sleep')
    p.add_argument('--runs', type=int, default=3)
    p.add_argument('--repeat', type=int, nargs='+', default=[1, 2, 4])
    p.add_argument('--max-seconds', type=float, default=30)
    p.add_argument('--max-tokens', type=int, default=256)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if min(a.chunk_ms, a.threads, a.decoder_threads, a.encoder_threads, a.runs, a.max_tokens, *a.repeat) < 1 or a.max_seconds <= 0:
        p.error('Positive timing, run, repetition and utterance limits required')
    if a.out.exists():
        p.error('Use a new output path to preserve evidence')
    import soundfile as sf
    from moonshine.matrix import BulkDevice
    from moonshine.model import load
    from moonshine.ort_decoder import Runtime
    from moonshine.streaming import Stream
    base, rate = sf.read(a.wav, dtype='float32')
    if rate != 16000 or base.ndim != 1 or not len(base) or not np.isfinite(base).all():
        p.error('Expected nonempty finite mono 16 kHz audio')
    if len(base)*max(a.repeat) > a.max_seconds*16000:
        p.error('Repeated input exceeds the utterance limit')
    chunk = a.chunk_ms*16
    results = {}
    for count in dict.fromkeys(a.repeat):
        samples = np.tile(base, count)
        results[str(count)] = {'repetitions': count, 'audio_seconds': len(samples)/16000,
            'sample_count': len(samples), 'audio_sha256': hashlib.sha256(samples.astype('<f4').tobytes()).hexdigest()}
    for backend in ('cpu-int8', 'oracle', 'fpga'):
        device = BulkDevice(ROOT/'build/native/libqnc_moonshine.so') if backend == 'fpga' else None
        try:
            before = time.perf_counter()
            model, processor, metadata = load(a.size, backend, device=device, threads=a.threads)
            runtime = Runtime(a.ort_decoder, metadata, threads=a.decoder_threads, scheduling=a.decoder_scheduling)
            encoder_runtime = None
            if a.ort_encoder:
                from moonshine.ort_encoder import Runtime as EncoderRuntime
                encoder_runtime = EncoderRuntime(a.ort_encoder, metadata, threads=a.encoder_threads,
                                                 scheduling=a.encoder_scheduling)
            initialization = time.perf_counter()-before
            for key, case in results.items():
                samples = np.tile(base, case['repetitions'])
                runs = []
                for index in range(0 if backend == 'oracle' else -1, 1 if backend == 'oracle' else a.runs):
                    stream = Stream(model, processor, a.max_seconds, a.max_tokens,
                                    decoder_runtime=runtime, encoder_runtime=encoder_runtime)
                    events = []
                    physical_before = device.stats() if device else None
                    before = time.perf_counter()
                    for offset in range(0, len(samples), chunk):
                        t = time.perf_counter()
                        event = stream.push(samples[offset:offset+chunk])
                        event['processing_seconds'] = time.perf_counter()-t
                        events.append(event)
                    t = time.perf_counter()
                    event = stream.finish()
                    event['processing_seconds'] = time.perf_counter()-t
                    events.append(event)
                    elapsed = time.perf_counter()-before
                    physical_after = device.stats() if device else None
                    runs.append({'run': index, 'seconds': elapsed, 'events': events,
                        'profile': stream.profile, 'decode_stats': stream.decode_stats,
                        'physical': {k: physical_after[k]-physical_before[k] for k in physical_before} if device else None})
                case[backend] = {'metadata': metadata, 'decoder_runtime': runtime.metadata,
                    'encoder_runtime': encoder_runtime.metadata if encoder_runtime else {'engine': 'torch'},
                    'initialization_seconds': initialization, 'runs': runs}
                print(backend, case['audio_seconds'], [r['seconds'] for r in runs], flush=True)
            del stream, model, processor, runtime, encoder_runtime
            gc.collect()
        finally:
            if device:
                device.close()
    for case in results.values():
        case.update(qualify(case))
    report = {'cases': results, 'size': a.size, 'chunk_ms': a.chunk_ms, 'threads': a.threads,
        'decoder_threads': a.decoder_threads, 'max_tokens': a.max_tokens, 'accuracy_qualified': False,
        'environment': {name: os.environ.get(name) for name in
                        ('OMP_WAIT_POLICY', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')},
        'note': 'Repeated audio measures duration scaling, not independent accuracy. Initialization and capture waits are excluded.'}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2)+'\n')
    if not all(c['realtime_execution_met'] for c in results.values()):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
