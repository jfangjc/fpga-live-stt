"""Transcribe one bounded WAV using the qualified KV260 physical runtime."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'software/latency'))


def validate_samples(count):
    frames = count // 160 + 1
    if count < 320 or frames > 256:
        raise ValueError('Expected 0.02 <= duration < 2.56 seconds at 16 kHz; split audio explicitly')
    return frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path, help='Uncompressed 16 kHz mono PCM WAV')
    parser.add_argument('--policy-context', type=float, choices=(0.5, 1.0, 2.5),
                        help='Use a saved policy; default selects the nearest measured duration')
    parser.add_argument('--out', type=Path, help='Optional JSON result (refuses overwrite)')
    args = parser.parse_args()
    if args.out and args.out.exists():
        parser.error('Output exists; choose a new output path')
    # Delay hardware/runtime imports so --help and input-bound tests work on hosts.
    from branch512_ab166_vf_benchmark import (AudioTimer, artifacts, bindings,
        choose, configure, make_session, read_audio)
    audio = read_audio(args.audio)
    validate_samples(len(audio))
    policy = json.loads((ROOT / 'reports/fused/branch512_ab166_vf_latency_policy.json').read_text())
    context = args.policy_context or min((0.5, 1.0, 2.5), key=lambda n: abs(n-len(audio)/16000))
    selected = next(row for row in policy['selected'] if row['context_seconds'] == context)
    config = selected['policy']
    start = time.perf_counter()
    items = artifacts()
    bound = bindings(items)
    for key, expected in policy.items():
        if key.endswith('_sha256') and key in bound and expected != bound[key]:
            raise RuntimeError('Qualified policy artifact changed: ' + key)
    old_affinity = os.sched_getaffinity(0)
    try:
        os.sched_setaffinity(0, {3})
        configure(config['irq_core'])
        runner = make_session(choose(items, 'fpga', config), config,
                              [items['boundary_library'], items['library']])
        timer = AudioTimer(items)
        initialization_seconds = time.perf_counter() - start
        result, _ = timer.call(runner, audio, 'fpga')
        # This command creates a new session: 24 registration ioctls precede
        # the 24 execution ioctls. The warm benchmark reuses those handles.
        if result['counters']['loads'] != 256 or result['counters']['ioctls'] != 48:
            raise RuntimeError('Physical work differs from the qualified cold graph: '+str(result['counters']))
        result.update(audio=str(args.audio.resolve()), audio_seconds=len(audio)/16000,
                      policy_context_seconds=context, initialization_seconds=initialization_seconds,
                      hardware_execution=True, execution_phase='cold', program_registration_included=True,
                      capture_qualified=False,
                      representative_wer_qualified=False, bindings=bound)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
    finally:
        os.sched_setaffinity(0, old_affinity)


if __name__ == '__main__':
    main()
