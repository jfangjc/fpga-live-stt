"""Compare paired streaming runs with the fastest measured CPU comparator.

Run inside run_moonshine_board.py. A missed target writes the evidence then exits 2.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]


def compare(cpu_reports, oracle, fpga, required_speedup=2):
    signature = ('audio_sha256', 'revision', 'size', 'chunk_ms', 'final_only', 'max_tokens', 'sample_count',
                 'draft_reuse', 'runtime_sources_sha256', 'torch_version', 'transformers_version', 'platform')
    for report in [*cpu_reports, oracle]:
        if any(report[k] != fpga[k] for k in signature):
            raise ValueError('Benchmark input/model/policy mismatch')
    for report in cpu_reports:
        if report['backend'] == 'cpu-int8' and report.get('decoder_runtime') != fpga.get('decoder_runtime'):
            raise ValueError('CPU INT8 comparator must use the same decoder runtime')
    if oracle.get('decoder_runtime') != fpga.get('decoder_runtime'):
        raise ValueError('Oracle and FPGA must use the same decoder runtime')
    if oracle.get('encoder_runtime') != fpga.get('encoder_runtime'):
        raise ValueError('Oracle and FPGA must use the same encoder runtime')
    for report in cpu_reports:
        if (report.get('encoder_runtime', {}).get('engine') == 'onnxruntime' and
                report.get('encoder_runtime') != fpga.get('encoder_runtime')):
            raise ValueError('Native CPU comparator must use matching encoder artifacts and precision')
    if oracle['backend'] != 'oracle' or fpga['backend'] != 'fpga' or oracle['scope'] != fpga['scope']:
        raise ValueError('Expected matching oracle and physical projection policies')
    if oracle['cpu_tail_int8'] != fpga['cpu_tail_int8']:
        raise ValueError('Oracle and FPGA must use the same CPU tail precision')
    if not cpu_reports or any(r['backend'] not in ('cpu', 'cpu-int8') for r in cpu_reports):
        raise ValueError('CPU comparator required')
    if not fpga.get('physical') or fpga['physical']['runs'] < 1:
        raise ValueError('No physical FPGA execution recorded')
    expected = [e['tokens'] for e in oracle['runs'][0]['events']]
    parity = all([e['tokens'] for e in run['events']] == expected for run in fpga['runs'])
    truncation = any(e.get('token_limit_reached', False) for r in [*cpu_reports, oracle, fpga]
                     for run in r['runs'] for e in run['events'] if e.get('final', True))
    partial_limits = any(e.get('token_limit_reached', False) for r in [*cpu_reports, oracle, fpga]
                        for run in r['runs'] for e in run['events'] if not e.get('final', True))
    fastest = min(cpu_reports, key=lambda r: r['p50_seconds'])
    speedup = fastest['p50_seconds'] / fpga['p50_seconds']
    float_reports = [r for r in cpu_reports if r['backend'] == 'cpu']
    if not float_reports:
        raise ValueError('Floating-point reference required for transcript comparison')
    reference_text = float_reports[0]['runs'][0]['text']
    float_equal = all(run['text'] == reference_text for run in fpga['runs'])
    cpu_equal = all(run['text'] == reference_text for run in fastest['runs'])
    def profile(report):
        return {k: statistics.median(r['profile'][k] for r in report['runs'])
                for k in report['runs'][0].get('profile', {})}
    duration = fpga['sample_count']/16000
    times = [run['total_processing_seconds'] for run in fpga['runs']
             if 'total_processing_seconds' in run]
    return {'cpu_backend': fastest['backend'], 'cpu_threads': fastest['threads'],
            'cpu_p50_seconds': fastest['p50_seconds'], 'fpga_p50_seconds': fpga['p50_seconds'],
            'speedup': speedup, 'target': required_speedup, 'oracle_tokens_equal': parity,
            'token_limit_reached': truncation, 'float_transcript_equal': float_equal,
            'cpu_comparator_transcript_equal': cpu_equal,
            'partial_token_limits_reached': partial_limits,
            'target_met': speedup >= required_speedup and parity and float_equal and cpu_equal and not truncation,
            'recording_seconds': duration,
            'fpga_realtime_factor': fpga['p50_seconds']/duration,
            'fpga_max_seconds': max(times) if times else None,
            'fpga_first_call_seconds': fpga.get('first_call_seconds'),
            'realtime_timing_met': fpga['p95_seconds'] < duration if 'p95_seconds' in fpga else False,
            'realtime_execution_met': bool(times) and max(times) < duration and parity and not truncation,
            'cpu_profile_p50': profile(fastest), 'fpga_profile_p50': profile(fpga),
            'float_cpu_text': cpu_reports[0]['runs'][0]['text'], 'fpga_text': fpga['runs'][0]['text'],
            'accuracy_qualified': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('wav', type=Path)
    p.add_argument('--out-dir', type=Path, required=True)
    p.add_argument('--size', choices=('small', 'tiny'), default='small')
    p.add_argument('--scope', choices=('frontend-ffn', 'encoder-ffn', 'encoder', 'all'), default='encoder-ffn')
    p.add_argument('--threads', type=int, nargs='+', default=[1, 2, 4])
    p.add_argument('--runs', type=int, default=3)
    p.add_argument('--chunk-ms', type=int, default=500)
    p.add_argument('--target', type=float, default=2)
    p.add_argument('--final-only', action='store_true')
    p.add_argument('--ort-decoder', type=Path)
    p.add_argument('--decoder-precision', choices=('float', 'int8'), default='int8')
    p.add_argument('--decoder-threads', type=int, default=2)
    p.add_argument('--decoder-scheduling', choices=('sleep', 'run-spin'), default='sleep')
    p.add_argument('--ort-encoder', type=Path)
    p.add_argument('--encoder-precision', choices=('float', 'int8'), default='int8')
    p.add_argument('--encoder-threads', type=int, default=4)
    p.add_argument('--encoder-scheduling', choices=('sleep', 'run-spin'), default='sleep')
    a = p.parse_args()
    if a.out_dir.exists():
        p.error('Use a new output directory to preserve benchmark evidence')
    if a.runs < 1 or min(a.threads) < 1 or a.target <= 0:
        p.error('Run count, thread count and target must be positive')
    a.out_dir.mkdir(parents=True)
    env = dict(os.environ, PYTHONPATH=str(ROOT/'software'))
    def run(backend, threads, count, native_encoder=False):
        name = backend+'-'+str(threads)+('-native-encoder' if native_encoder else '')
        out = a.out_dir/(name+'.json')
        cmd = [sys.executable, '-m', 'moonshine.transcribe', str(a.wav.resolve()), '--size', a.size,
               '--backend', backend, '--threads', str(threads), '--runs', str(count), '--scope', a.scope,
               '--warmup', '0' if backend == 'oracle' else '1',
               '--chunk-ms', str(a.chunk_ms), '--out', str(out.resolve())]
        if a.final_only: cmd.append('--final-only')
        # Keep the float reference independent of native decoder quantization.
        if a.ort_decoder and backend != 'cpu':
            cmd.extend(['--ort-decoder', str(a.ort_decoder.resolve()), '--decoder-precision', a.decoder_precision,
                        '--decoder-threads', str(a.decoder_threads), '--decoder-scheduling', a.decoder_scheduling])
        if native_encoder:
            cmd.extend(['--ort-encoder', str(a.ort_encoder.resolve()), '--encoder-precision', a.encoder_precision,
                        '--encoder-threads', str(a.encoder_threads), '--encoder-scheduling', a.encoder_scheduling])
        with (a.out_dir/(name+'.log')).open('w') as log:
            subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        return json.loads(out.read_text())
    cpu = [run(backend, n, a.runs) for backend in ('cpu', 'cpu-int8') for n in a.threads]
    if a.ort_encoder:
        cpu += [run('cpu-int8', n, a.runs, True) for n in a.threads]
    preferred_threads = min(cpu, key=lambda report: report['p50_seconds'])['threads']
    oracle = run('oracle', preferred_threads, 1, bool(a.ort_encoder))
    fpga = run('fpga', preferred_threads, a.runs, bool(a.ort_encoder))
    result = compare(cpu, oracle, fpga, a.target)
    (a.out_dir/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['target_met'] else 2)


if __name__ == '__main__':
    main()
