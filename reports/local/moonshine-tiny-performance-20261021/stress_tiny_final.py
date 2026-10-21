"""Board evidence only: actual short clips and repeated-audio scaling checks."""
import hashlib, json, time
from pathlib import Path
import numpy as np
import soundfile as sf
from moonshine.matrix import BulkDevice
from moonshine.model import load
from moonshine.ort_decoder import Runtime
from moonshine.streaming import Stream

root = Path('/home/ubuntu/kv260-asr-mvp-20261015/reports/test-inputs')
base, rate = sf.read(root/'speech_25.wav', dtype='float32')
assert rate == 16000
cases = [('speech_25.wav', base)]
for name in ():
    audio, rate = sf.read(root/name, dtype='float32'); assert rate == 16000
    cases.append((name, audio))
cases += [('repeat-5s', np.tile(base, 2)), ('repeat-10s', np.tile(base, 4))]
results = {}
for backend in ('oracle', 'fpga'):
    device = BulkDevice('build/native/libqnc_moonshine.so') if backend == 'fpga' else None
    try:
        model, processor, meta = load('tiny', backend, device=device, threads=2)
        runtime = Runtime('build/tiny-decoder-v2', meta, threads=4)
        for name, audio in cases:
            runs = []
            for run in range(-1 if backend == 'fpga' else 0, 3 if backend == 'fpga' else 1):
                stream = Stream(model, processor, decoder_runtime=runtime)
                events = []
                before = time.perf_counter()
                for start in range(0, len(audio), 16000):
                    events.append(stream.push(audio[start:start+16000]))
                events.append(stream.finish())
                elapsed = time.perf_counter()-before
                runs.append({'run': run, 'seconds': elapsed, 'events': events, 'profile': stream.profile})
            results.setdefault(name, {'audio_seconds': len(audio)/16000,
                'audio_sha256': hashlib.sha256(audio.astype('<f4').tobytes()).hexdigest()})[backend] = {
                'metadata': meta, 'decoder_runtime': runtime.metadata, 'runs': runs}
            print(backend, name, [r['seconds'] for r in runs], flush=True)
    finally:
        if device is not None:
            physical = device.stats(); device.close()
for name, result in results.items():
    expected = [e['tokens'] for e in result['oracle']['runs'][0]['events']]
    actual = result['fpga']['runs']
    result['oracle_tokens_equal'] = all([e['tokens'] for e in r['events']] == expected for r in actual)
    result['final_token_limit_reached'] = any(r['events'][-1].get('token_limit_reached') for r in actual)
    result['all_warm_runs_realtime'] = all(r['seconds'] < result['audio_seconds'] for r in actual if r['run'] >= 0)
report = {'cases': results, 'physical': physical, 'accuracy_qualified': False, 'chunk_ms': 1000, 'decoder_threads': 4,
    'note': '5s and 10s cases repeat the 2.5s recording; these are scaling tests, not an independent accuracy corpus.'}
Path('reports/local/tiny-ort-final-durations.json').write_text(json.dumps(report, indent=2)+'\n')
if not all(r['oracle_tokens_equal'] and r['all_warm_runs_realtime'] and not r['final_token_limit_reached'] for r in results.values()):
    raise SystemExit(2)
