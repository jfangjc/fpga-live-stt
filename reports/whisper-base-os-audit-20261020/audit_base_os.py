"""Replay preserved base qualification, then check base on the newer backend."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def environment(binary):
    root = Path(binary).resolve().parent.parent
    dirs = [root/'src', root/'ggml/src', root/'ggml/src/ggml-cpu']
    return dict(os.environ, LD_LIBRARY_PATH=':'.join(str(p) for p in dirs if p.is_dir()))


def libraries(binary):
    output = subprocess.check_output(['ldd', str(Path(binary).resolve())], env=environment(binary), text=True)
    return {p: sha(p) for p in re.findall(r'=> (/\S+) \(', output)}


def sample():
    result = {'utc': datetime.now(timezone.utc).isoformat()}
    for name in ('stat', 'meminfo', 'vmstat', 'diskstats', 'loadavg', 'pressure/cpu', 'pressure/io', 'pressure/memory'):
        p = Path('/proc')/name
        if p.exists():
            result[name] = p.read_text()
    clock = Path('/sys/kernel/debug/clk/clk_summary')
    result['cpu_clock'] = [line.strip() for line in clock.read_text().splitlines()
                           if re.search(r'\bacpu\b', line)] if clock.exists() else []
    result['temperatures'] = {str(p): p.read_text().strip()
                              for p in Path('/sys/class/thermal').glob('thermal_zone*/temp')}
    result['processes'] = []
    for p in Path('/proc').glob('[0-9]*'):
        try:
            if (p/'comm').read_text().strip() == 'whisper-cli':
                result['processes'].append({'pid': int(p.name), 'stat': (p/'stat').read_text(),
                    'io': (p/'io').read_text(), 'status': (p/'status').read_text(),
                    'command': (p/'cmdline').read_bytes().replace(b'\0', b' ').decode()})
        except (FileNotFoundError, ProcessLookupError):
            pass
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work', type=Path, required=True)
    ap.add_argument('--reference', type=Path, required=True)
    a = ap.parse_args()
    work = a.work.resolve()
    if os.geteuid() != 0:
        ap.error('Run as root for managed FPGA sessions and telemetry')
    state_path = work/'state.json'
    if state_path.exists():
        ap.error('Use new output paths')
    old = Path('/home/ubuntu/whisper-kv260')
    new = Path('/home/ubuntu/whisper-small-kv260-20261020')
    release = Path('/home/ubuntu/kv260-asr-mvp-clean-20261015')
    reference = json.loads(a.reference.read_text())
    baseline = reference['baseline']
    state = {'pid': os.getpid(), 'status': 'running', 'phase': 'preflight'}

    def phase(name):
        state.update(phase=name, started=datetime.now(timezone.utc).isoformat())
        state_path.write_text(json.dumps(state, indent=2)+'\n')
        print(json.dumps(state), flush=True)

    def monitor():
        with (work/'telemetry.jsonl').open('a') as stream:
            stream.write(json.dumps({'phase': state['phase'], **sample()})+'\n')

    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'Interrupted by signal {signum}')

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    def execute(command, log, cwd):
        with (work/log).open('w') as stream:
            child = subprocess.Popen(list(map(str, command)), cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
            try:
                while child.poll() is None:
                    monitor()
                    time.sleep(5)
            except BaseException:
                child.terminate()
                child.wait(timeout=90)  # allow the hardware supervisor to restore
                raise
            if child.returncode:
                raise RuntimeError(f'{state["phase"]} exited {child.returncode}; inspect {log}')

    def session(name, command, cwd):
        execute([sys.executable, old/'final-source/software/whisper/hardware_session.py', '--release', release,
                 '--expected-app', 'k26-starter-kits', '--evidence', work/(name+'.session.json'), '--',
                 '/usr/bin/time', '-v', '-o', work/(name+'.total-time.txt'), *command], name+'.progress.jsonl', cwd)

    try:
        phase('preflight')
        sys.path.insert(0, str(old/'final-source/software/whisper'))
        from hardware_session import active_app
        if active_app() != 'k26-starter-kits' or Path('/sys/module/qn_tile').exists():
            raise RuntimeError('Require idle starter application without qn_tile')
        if sample()['processes']:
            raise RuntimeError('Another Whisper CLI is active')
        matched = {}
        for name, expected in baseline['artifacts'].items():
            path = Path(name) if Path(name).is_absolute() else old/name
            actual = sha(path)
            if actual != expected:
                raise RuntimeError('Preserved artifact differs from original: '+str(path))
            matched[str(path)] = actual
        for name, expected in reference['preserved_harness'].items():
            if sha(old/'final-source'/name) != expected:
                raise RuntimeError('Preserved packaged harness differs: '+name)
        deps = {tag: libraries(old/f'build-{tag}/bin/whisper-cli') for tag in ('cpu', 'hybrid')}
        if deps != baseline['dynamic_libraries']:
            raise RuntimeError('Original library identities changed; inspect before inference')
        identities = {'original_artifacts': matched, 'original_libraries': deps,
                      'kernel': os.uname().release, 'os_release': Path('/etc/os-release').read_text(),
                      'cpu_info': subprocess.check_output(['lscpu'], text=True),
                      'disk_layout': subprocess.check_output(['lsblk', '-o', 'NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS'], text=True)}
        (work/'identities.json').write_text(json.dumps(identities, indent=2)+'\n')
        phase('idle_os_sample')
        for _ in range(3):
            monitor()
            time.sleep(5)
        audios = [row['audio'] for row in baseline['clips']]
        models = ['model-base.bin', 'model-base-q8_0.bin', 'model-base-q5_0.bin']
        phase('exact_original_replay')
        command = [sys.executable, old/'final-source/software/whisper/benchmark.py',
                   '--cpu', 'build-cpu/bin/whisper-cli', '--hybrid', 'build-hybrid/bin/whisper-cli',
                   '--model', 'model-base-q8_0.bin', '--fpga-attention', '--cpu-unfused-only',
                   '--repeats', '3', '--warmup', '1', '--out', work/'replay_results']
        for model in models:
            command.extend(['--cpu-model', model])
        for audio in audios:
            command.extend(['--audio', audio])
        session('original_replay', command, old)
        phase('current_backend_cache_control')
        command = [sys.executable, new/'source/software/whisper/benchmark.py',
                   '--cpu', new/'build-cpu/bin/whisper-cli', '--hybrid', new/'build-hybrid/bin/whisper-cli',
                   '--model', old/'model-base-q8_0.bin', '--cpu-model', old/'model-base-q8_0.bin',
                   '--fpga-attention', '--cpu-unfused-only', '--preload-model', '--resource-timing',
                   '--repeats', '3', '--warmup', '1', '--out', work/'current_results']
        for audio in audios:
            command.extend(['--audio', audio])
        session('current_backend', command, work)
        phase('postflight')
        for path, expected in matched.items():
            if sha(path) != expected:
                raise RuntimeError('Original artifact changed during audit: '+path)
        if deps != {tag: libraries(old/f'build-{tag}/bin/whisper-cli') for tag in ('cpu', 'hybrid')}:
            raise RuntimeError('Original libraries changed during audit')
        board = {'active_app': active_app(), 'qn_tile_loaded': Path('/sys/module/qn_tile').exists(),
                 'fpga_state': Path('/sys/class/fpga_manager/fpga0/state').read_text().strip()}
        if board != {'active_app': 'k26-starter-kits', 'qn_tile_loaded': False, 'fpga_state': 'operating'}:
            raise RuntimeError('Final board state is not restored')
        (work/'board_check.json').write_text(json.dumps(board, indent=2)+'\n')
        messages = subprocess.run(['dmesg', '--level=err,warn'], capture_output=True, text=True)
        relevant = [line for line in messages.stdout.splitlines() if re.search(
            r'mmc|timeout|thermal|throttl|out of memory|oom|I/O error|ext4|dma', line, re.I)]
        (work/'kernel-storage-memory-warnings.json').write_text(json.dumps(
            {'command_exit': messages.returncode, 'matching_warnings': relevant}, indent=2)+'\n')
        state.update(status='complete', original_artifacts_unchanged=True)
        phase('complete')
    except BaseException as error:
        state.update(status='failed', error=str(error))
        phase('failed')
        raise


if __name__ == '__main__':
    main()
