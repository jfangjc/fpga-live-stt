"""Independent board timing audit; keeps the qualified builds unchanged."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def machine():
    clock = Path('/sys/kernel/debug/clk/clk_summary')
    return {
        'uptime': Path('/proc/uptime').read_text().strip(),
        'loadavg': Path('/proc/loadavg').read_text().strip(),
        'cpu_stat': Path('/proc/stat').read_text().splitlines()[0],
        'cpu_clock': [line.strip() for line in clock.read_text().splitlines()
                      if re.search(r'\bacpu\b', line)] if clock.exists() else [],
        'temperatures': {str(p): p.read_text().strip()
                         for p in Path('/sys/class/thermal').glob('thermal_zone*/temp')},
        'meminfo': Path('/proc/meminfo').read_text(),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work', type=Path, required=True)
    ap.add_argument('--release', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    a.work, a.out = a.work.resolve(), a.out.resolve()
    a.out.mkdir(parents=True, exist_ok=False)
    source = a.work/'source/software/whisper'
    sys.path.insert(0, str(source))
    from benchmark import runtime_environment, dependencies
    report = {'status': 'running', 'stage': 'preflight', 'runs': [],
              'machine_start': machine(), 'scope': 'Independent fresh CLI processes; OS model file pre-read before each timed command; full 1500-position encoder context',
              'temperature_note': 'Empty temperatures means sensors unavailable, not a measured safe temperature.'}

    def save():
        (a.out/'audit.json').write_text(json.dumps(report, indent=2)+'\n')

    def command(cmd, name, env=None):
        report['stage'] = name
        save()
        with (a.out/(name+'.stdout')).open('w') as stdout, (a.out/(name+'.stderr')).open('w') as stderr:
            child = subprocess.Popen(list(map(str, cmd)), stdout=stdout, stderr=stderr, env=env)
            while child.poll() is None:
                status = {'pid': child.pid, 'stage': name, 'machine': machine()}
                status['processes'] = subprocess.check_output(
                    ['ps', '-eo', 'pid,ppid,pcpu,rss,comm', '--sort=-pcpu'], text=True).splitlines()[:12]
                with (a.out/'monitor.jsonl').open('a') as stream:
                    stream.write(json.dumps(status)+'\n')
                time.sleep(10)
            if child.returncode:
                raise RuntimeError(f'{name} exited {child.returncode}; inspect stderr')

    try:
        model = a.work/'models/ggml-large-v3-turbo-q8_0.bin'
        audio = a.work/'latency-three/audio/6930-75918-0000.wav'
        for variant, binary in [('cpu_original', a.work/'build-cpu/bin/whisper-cli'),
                                ('hybrid', a.work/'build-hybrid/bin/whisper-cli'),
                                ('cpu_native', a.out/'build-native/bin/whisper-cli')]:
            if variant == 'cpu_native':
                cmake = a.work/'.venv/bin/cmake'
                command([cmake, '-S', a.work/'upstream', '-B', a.out/'build-native',
                         '-DCMAKE_BUILD_TYPE=Release', '-DGGML_NATIVE=ON', '-DGGML_OPENMP=OFF',
                         '-DGGML_BLAS=OFF', '-DWHISPER_BUILD_TESTS=OFF', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
                         '-DCMAKE_C_FLAGS=-mtune=cortex-a53', '-DCMAKE_CXX_FLAGS=-mtune=cortex-a53'], 'configure_native')
                command([cmake, '--build', a.out/'build-native', '--target', 'whisper-cli', '-j', '3'], 'build_native')
            # Equalize the model's filesystem-cache opportunity outside the timer.
            with model.open('rb') as stream:
                while stream.read(8*1024*1024):
                    pass
            env = dict(runtime_environment(binary), WHISPER_KV260='1' if variant == 'hybrid' else '0',
                       WHISPER_KV260_ATTENTION='1' if variant == 'hybrid' else '0', WHISPER_KV260_DECODE='0')
            cli = [binary, '-m', model, '-f', audio, '-t', '4', '-l', 'en', '-nt', '-ng', '-nf', '-bs', '1', '-bo', '1', '-nfa']
            timed = ['/usr/bin/time', '-v', '-o', a.out/(variant+'.time.txt'), *cli]
            if variant == 'hybrid':
                timed = [sys.executable, source/'hardware_session.py', '--release', a.release,
                         '--expected-app', 'k26-starter-kits', '--evidence', a.out/'hybrid.session.json', '--', *timed]
            start = time.perf_counter()
            command(timed, variant, env)
            outer = time.perf_counter()-start
            log = (a.out/(variant+'.stderr')).read_text()
            stages = {key: float(value)/1000 for key, value in re.findall(
                r'whisper_print_timings:\s*(load|mel|encode|decode|batchd|total) time\s*=\s*([0-9.]+) ms', log)}
            if not stages.get('encode', 0) > 0:
                raise RuntimeError('Missing encoder timing')
            if variant == 'hybrid' and not re.search(r'KV260_STATS calls=264 .*attention_calls=64', log):
                raise RuntimeError('Full physical partition not observed')
            report['runs'].append({'variant': variant, 'outer_supervisor_seconds_including_polling_and_hardware_setup': outer,
                                   'stages_seconds': stages, 'binary_sha256': sha(binary),
                                   'model_sha256': sha(model), 'audio_sha256': sha(audio),
                                   'libraries': dependencies(binary), 'resource_time': (a.out/(variant+'.time.txt')).read_text(),
                                   'stdout': (a.out/(variant+'.stdout')).read_text()})
            save()
        report['status'] = 'complete'
        report['stage'] = 'complete'
    except BaseException as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        report['machine_end'] = machine()
        save()


if __name__ == '__main__':
    main()
