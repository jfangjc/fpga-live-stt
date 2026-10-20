"""Randomized paired end-to-end CLI benchmark; includes process/model loading.

Compare the fastest measured CPU model to physical FPGA execution. No graph
timings or kernel microbenchmarks can satisfy the 2x gate on their own.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import statistics
import subprocess
import struct
import time
from model_spec import SPECS


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def check_model(model):
    with model.open('rb') as f:
        data = f.read(48)
    if len(data)!=48:
        raise ValueError(f'Truncated GGML model: {model}')
    header = struct.unpack('<12i', data)
    for spec in SPECS.values():
        if header[:11]==spec['header']:
            return spec['id']
    raise ValueError(f'Unsupported multilingual Whisper GGML architecture: {model}: {header}')


def runtime_environment(binary):
    env = dict(os.environ)
    root = binary.resolve().parent.parent
    directories = [root/'src',root/'ggml/src']
    if all(p.is_dir() for p in directories):
        optional = root/'ggml/src/ggml-cpu'
        if optional.is_dir():
            directories.append(optional)
        env['LD_LIBRARY_PATH'] = ':'.join(map(str,directories)) + (':'+env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    return env


def run(binary, model, audio, threads, physical, log, language='en', fpga_decoder=False,
        fpga_attention=False, flash_attention=True, resource_timing=False):
    env = dict(runtime_environment(binary), WHISPER_KV260='1' if physical else '0',
               WHISPER_KV260_DECODE='1' if physical and fpga_decoder else '0',
               WHISPER_KV260_ATTENTION='1' if physical and fpga_attention else '0')
    command = [str(binary.resolve()), '-m', str(model.resolve()), '-f', str(audio.resolve()),
               '-t', str(threads), '-l', language, '-nt', '-ng', '-nf', '-bs', '1', '-bo', '1']
    if flash_attention and not (physical and fpga_attention):
        command.append('-fa')
    else:
        command.append('-nfa')
    resource_log = log.with_suffix('.time.txt')
    if resource_timing:
        command = ['/usr/bin/time','-v','-o',str(resource_log.resolve()),*command]
    start = time.perf_counter()
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    elapsed = time.perf_counter() - start
    log.write_text(result.stderr + '\nSTDOUT\n' + result.stdout)
    if result.returncode:
        raise RuntimeError(f'Inference exited {result.returncode}; see {log}')
    stats = re.search(r'KV260_STATS calls=(\d+).*ioctls=(\d+).*loads=(\d+).*runs=(\d+)', result.stderr)
    if physical and (not stats or min(map(int, stats.groups())) <= 0):
        raise RuntimeError('Physical execution requested without positive DMA evidence')
    attention = re.search(r'attention_calls=(\d+)',result.stderr)
    if physical and fpga_attention and (not attention or int(attention[1]) == 0):
        raise RuntimeError('FPGA attention requested without physical attention execution')
    return {'seconds': elapsed, 'text': result.stdout.strip(), 'log': str(log),
            'resource_log': str(resource_log) if resource_timing else None,
            'physical': physical, 'fpga_decoder': physical and fpga_decoder,
            'fpga_attention': physical and fpga_attention,
            'flash_attention': flash_attention and not (physical and fpga_attention),
            'physical_counters': dict(zip(('matrix_operations','ioctls','weight_loads','time_tiles'),map(int,stats.groups()))) if stats else None}


def summarize(rows):
    values = sorted(r['seconds'] for r in rows)
    return {'p50_seconds': statistics.median(values),
            'p95_seconds': values[min(len(values)-1, int(len(values)*0.95))], 'runs': len(values)}


def dependencies(binary):
    """Bind local dynamic libraries as well as the CLI executable."""
    output = subprocess.check_output(['ldd', str(binary.resolve())], text=True,env=runtime_environment(binary))
    paths = re.findall(r'=> (/\S+) \(', output)
    return {path: sha(Path(path)) for path in paths if Path(path).is_file()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cpu', required=True, type=Path)
    ap.add_argument('--hybrid', required=True, type=Path)
    ap.add_argument('--cpu-model', required=True, type=Path, action='append')
    ap.add_argument('--model', required=True, type=Path)
    inputs = ap.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--audio', type=Path, action='append')
    inputs.add_argument('--manifest',type=Path)
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--repeats', type=int, default=5)
    ap.add_argument('--warmup', type=int, default=1)
    ap.add_argument('--preload-model', action='store_true', help='Read model file outside each CLI timer; model/context initialization remains timed')
    ap.add_argument('--resource-timing', action='store_true', help='Also record GNU time wall/user/system/RSS for every CLI')
    ap.add_argument('--fpga-decoder', action='store_true')
    ap.add_argument('--fpga-attention', action='store_true')
    attention_group = ap.add_mutually_exclusive_group()
    attention_group.add_argument('--cpu-no-flash', action='store_true', help='Also screen unfused CPU attention')
    attention_group.add_argument('--cpu-unfused-only', action='store_true')
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args()
    if a.manifest:
        rows = [json.loads(line) for line in a.manifest.read_text().splitlines() if line.strip()]
        if not rows or any(row['role']!='evaluation' for row in rows):
            ap.error('Expected a nonempty evaluation manifest')
        a.audio = [(a.manifest.parent/row['audio']).resolve() for row in rows]
        if any(sha(path)!=row['wav_sha256'] for path,row in zip(a.audio,rows)):
            ap.error('Evaluation audio hash mismatch')
    if a.repeats < 1 or a.warmup < 0:
        ap.error('repeats must be positive; warmup must be nonnegative')
    identity = check_model(a.model)
    if any(check_model(model)!=identity for model in a.cpu_model):
        ap.error('CPU and hybrid models must have the same Whisper architecture')
    if len({sha(audio) for audio in a.audio}) != len(a.audio):
        ap.error('Duplicate evaluation audio')
    a.out.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'End-to-end process time including model load, WAV, frontend, encoder, decoder, text and DMA',
              'model':identity, 'language': 'en', 'decoding': 'greedy beam=1 best_of=1 temperature=0 no fallback; attention mode recorded per run',
              'threads': a.threads, 'warmup': a.warmup, 'repeats': a.repeats,
              'model_file_pre_read': a.preload_model, 'external_resource_timing': a.resource_timing,
              'fpga_decoder_dense': a.fpga_decoder,
              'fpga_attention': a.fpga_attention,
              'cpu_attention_mode': 'unfused' if a.cpu_unfused_only else ('both' if a.cpu_no_flash else 'fused'),
              'artifacts': {str(p): sha(p) for p in [a.cpu, a.hybrid, a.model, *a.cpu_model, *a.audio]},
              'dynamic_libraries': {'cpu': dependencies(a.cpu), 'hybrid': dependencies(a.hybrid)},
              'clips': [], 'qualified_2x': False}
    if a.manifest:
        report['manifest'] = {'path':str(a.manifest),'sha256':sha(a.manifest)}
    rng = random.Random(260)
    for clip, audio in enumerate(a.audio):
        suffix = '_no_flash' if a.cpu_unfused_only else ''
        variants = [(f'cpu_{i}{suffix}', a.cpu, model, False) for i, model in enumerate(a.cpu_model)]
        if a.cpu_no_flash:
            variants += [(f'cpu_{i}_no_flash',a.cpu,model,False) for i,model in enumerate(a.cpu_model)]
        variants.append(('hybrid', a.hybrid, a.model, True))
        rows = {v[0]: [] for v in variants}
        for iteration in range(-a.warmup, a.repeats):
            order = list(variants)
            rng.shuffle(order)
            for name, binary, model, physical in order:
                if a.preload_model:
                    print(json.dumps({'event':'preload','clip':str(audio),'iteration':iteration,'variant':name}),flush=True)
                    with model.open('rb') as stream:
                        while stream.read(8*1024*1024):
                            pass
                print(json.dumps({'event':'start','clip':str(audio),'iteration':iteration,'variant':name}),flush=True)
                row = run(binary, model, audio, a.threads, physical,
                          a.out / f'{clip}_{iteration}_{name}.log', fpga_decoder=a.fpga_decoder,
                          fpga_attention=a.fpga_attention,flash_attention=not name.endswith('_no_flash'),resource_timing=a.resource_timing)
                print(json.dumps({'clip': str(audio), 'iteration': iteration, 'variant': name, **row}), flush=True)
                if iteration >= 0:
                    rows[name].append(row)
        summary = {name: summarize(v) for name, v in rows.items()}
        best = min((name for name in rows if name != 'hybrid'), key=lambda n: summary[n]['p50_seconds'])
        speedup = summary[best]['p50_seconds']/summary['hybrid']['p50_seconds']
        # Text parity is a smoke check. WER qualification needs a held-out corpus.
        reference = rows[variants[0][0]][0]['text']
        same_text = all(row['text'] == reference for row in rows['hybrid'])
        report['clips'].append({'audio': str(audio), 'rows': rows, 'summary': summary,
                                'best_cpu': best, 'speedup': speedup, 'text_parity': same_text,
                                'timing_2x': speedup >= 2})
        (a.out / 'results.json').write_text(json.dumps(report, indent=2)+'\n')
    report['all_clips_timing_2x'] = all(c['timing_2x'] for c in report['clips'])
    if any(sha(Path(path))!=digest for path,digest in report['artifacts'].items()):
        raise RuntimeError('Input artifacts changed during measurement')
    if {'cpu':dependencies(a.cpu),'hybrid':dependencies(a.hybrid)}!=report['dynamic_libraries']:
        raise RuntimeError('Dynamic libraries changed during measurement')
    report['artifacts_unchanged_after_run'] = True
    report['accuracy_status'] = 'Corpus WER not measured; prototype remains unqualified'
    (a.out / 'results.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
