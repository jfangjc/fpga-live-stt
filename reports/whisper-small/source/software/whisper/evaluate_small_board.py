"""Isolated Whisper small measurements using the frozen numerical backend."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work', type=Path, required=True)
    ap.add_argument('--release', type=Path, required=True)
    ap.add_argument('--resume', action='store_true', help='Resume an interrupted preparation before any measurement output exists')
    args = ap.parse_args()
    work = args.work.resolve()
    harness = Path(__file__).resolve().parent
    if os.geteuid() != 0:
        ap.error('Run as root for the managed hardware sessions')
    state_file = work/'pipeline_state.json'
    if state_file.exists() and not args.resume:
        ap.error('Refusing to overwrite existing experiment state')
    if args.resume:
        old = json.loads(state_file.read_text())
        if old['status'] != 'failed' or any((work/name).exists() for name in
                ('parallel_session.json','cpu-q8-smoke.json','validation_results','latency_results')):
            ap.error('Resume is limited to interrupted model preparation without measurement evidence')
        state_file.rename(work/'interrupted_preparation_state.json')
    state = {'pid': os.getpid(), 'status': 'running', 'phase': 'preflight'}

    def phase(name, total=None):
        state.update(phase=name, total_runs=total, phase_started=datetime.now(timezone.utc).isoformat())
        state_file.write_text(json.dumps(state, indent=2)+'\n')
        print(json.dumps(state), flush=True)

    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'Interrupted by signal {signum}')

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    def execute(command, log, allowed=(0,)):
        with (work/log).open('w') as stream:
            child = subprocess.Popen(list(map(str, command)), cwd=work, stdout=stream, stderr=subprocess.STDOUT)
            try:
                code = child.wait()
            except BaseException:
                child.terminate()
                child.wait(timeout=90)  # allow hardware_session to restore the board
                raise
        if code not in allowed:
            raise RuntimeError(f'{state["phase"]} exited {code}; inspect {log}')
        return code

    def session(evidence, command, log):
        return execute([sys.executable, harness/'hardware_session.py', '--release', args.release.resolve(),
                        '--expected-app', 'k26-starter-kits', '--evidence', evidence, '--', *command], log)

    model = 'models/ggml-small-q8_0.bin'
    sample = work/'latency-three/audio/6930-75918-0000.wav'
    common = [sys.executable, harness/'benchmark.py', '--cpu', 'build-cpu/bin/whisper-cli',
              '--hybrid', 'build-hybrid/bin/whisper-cli', '--model', model, '--fpga-attention',
              '--preload-model', '--resource-timing']
    try:
        phase('download_model')
        import hashlib
        partial = work/'models/ggml-small.bin.partial'
        final = work/'models/ggml-small.bin'
        if not final.exists():
            execute(['curl', '-L', '--fail', '--retry', '3', '-C', '-', '-o', 'models/ggml-small.bin.partial',
                     'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin'], 'download.log')
        with (final if final.exists() else partial).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha1').hexdigest() != '55356645c2b361a969dfd0ef2c5a50d530afd8d5':
                raise RuntimeError('Official small checkpoint SHA1 mismatch')
        if not final.exists():
            partial.rename(final)
        phase('quantize_models')
        for suffix in ('q8_0', 'q5_0'):
            execute(['build-cpu/bin/whisper-quantize', 'models/ggml-small.bin',
                     f'models/ggml-small-{suffix}.bin', suffix], suffix+'-quantize.log')
        execute([sys.executable, harness/'write_model_manifest.py', '--work', work,
                 '--model', 'small', '--out', 'model_manifest.json'], 'model-provenance.log')
        phase('physical_arithmetic')
        session('parallel_session.json', [work/'.venv/bin/python', harness/'test_physical_matrix.py',
                '--library', 'libqnc_parallel.so', '--ggml', '--out', 'parallel_conformance.json'], 'parallel_progress.log')
        phase('cpu_attention_reference')
        # Pre-read outside the CLI timer, matching the repeated benchmark policy.
        with (work/model).open('rb') as stream:
            while stream.read(8*1024*1024):
                pass
        execute([sys.executable, harness/'transcribe.py', sample, '--binary', 'build-cpu/bin/whisper-cli',
                 '--model', model, '--mode', 'cpu', '--language', 'en', '--out', 'cpu-q8-smoke.json'], 'cpu-smoke-progress.log')
        phase('cpu_attention_screen')
        execute([sys.executable, harness/'screen_attention.py', '--cpu', 'build-cpu/bin/whisper-cli',
                 '--model', model, '--audio', sample, '--reference', 'cpu-q8-smoke.json',
                 '--out', 'attention_screen.json'], 'attention-screen-progress.log')
        screen = json.loads((work/'attention_screen.json').read_text())
        phase('accuracy', 20)
        session('validation_session.json', [*common, '--cpu-unfused-only', '--cpu-model', 'models/ggml-small.bin',
                '--manifest', 'validation-ten/evaluation.jsonl', '--repeats', '1', '--warmup', '0',
                '--out', 'validation_results'], 'validation_progress.jsonl')
        execute([sys.executable, harness/'evaluate_report.py', 'validation_results/results.json',
                 '--manifest', 'validation-ten/evaluation.jsonl', '--out', 'validation_wer.json'], 'validation-scoring.log')
        # Preserve and report performance even if the eventual WER or 2x gate fails.
        both_modes = screen['selected'] == 'fused'
        phase('latency', 63 if both_modes else 36)
        session('latency_session.json', [*common, '--cpu-no-flash' if both_modes else '--cpu-unfused-only',
                '--cpu-model', 'models/ggml-small.bin', '--cpu-model', model,
                '--cpu-model', 'models/ggml-small-q5_0.bin', '--manifest', 'latency-three/evaluation.jsonl',
                '--repeats', '3', '--warmup', '0', '--out', 'latency_results'], 'latency_progress.jsonl')
        phase('scoring')
        execute([sys.executable, harness/'evaluate_report.py', 'latency_results/results.json',
                 '--manifest', 'latency-three/evaluation.jsonl', '--out', 'latency_wer.json'], 'latency-scoring.log')
        code = execute([sys.executable, harness/'qualify.py', '--work', work, '--out', 'qualification.json'],
                       'qualification-progress.log', allowed=(0, 1))
        if not (work/'qualification.json').exists():
            raise RuntimeError('Qualification failed without a report')
        state.update(status='complete', prototype_gates_passed=(code == 0),
                     live_streaming_qualified=False, note='Fixed-file full-context results; no microphone trial')
        phase('complete')
    except BaseException as error:
        state.update(status='failed', error=str(error))
        phase('failed')
        raise


if __name__ == '__main__':
    main()
