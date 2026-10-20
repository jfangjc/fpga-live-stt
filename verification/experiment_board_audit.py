"""Read-only independent audit of the supplied performance experiment reports."""
import hashlib
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def percentile(values, q):
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

def main():
    paths = {name: ROOT / 'reports' / (name + '-experiment-board.json')
             for name in ('native', 'physical', 'cpu', 'hybrid')}
    reports = {name: json.loads(path.read_text()) for name, path in paths.items()}
    native, physical, cpu, hybrid = (reports[name] for name in paths)
    checks = {}
    checks['native_checks_all_true'] = all(
        value is True for test in native['checks'] for key, value in test.items()
        if key in ('exact_integer_match', 'fused_float_scaling_exact', 'run_after_invalidate_rejected'))
    checks['native_hardware_execution'] = native['hardware_execution'] is True
    proof = physical['physical_vs_numerical_int8_implementation_parity']
    flags = ('passed', 'shapes_equal', 'finite', 'encoded_lengths_equal', 'encoded_lengths_valid',
             'logits_within_tolerance', 'transcripts_match', 'positive_physical_dma_work')
    checks['physical_parity_flags_all_true'] = all(proof[key] is True for key in flags)
    checks['physical_exact_logits'] = proof['max_abs_logprob_error'] == 0
    checks['physical_transcripts_match'] = physical['transcripts_match'] is True
    checks['physical_hardware_execution'] = physical['hardware_execution'] is True
    checks['native_binary_hash_consistent_across_reports'] = (
        native['native_library_sha256'] == physical['metadata']['native_library_sha256']
        == hybrid['metadata']['native_library_sha256'])
    checks['physical_report_hash_binding'] = (
        hybrid['metadata']['physical_quantized_graph_parity_report_sha256'] == sha(paths['physical']))
    checks['original_report_hash_binding'] = all(
        report['metadata']['original_model_output_parity_report_sha256']
        == sha(ROOT / 'reports/nemo_full_validation.json') for report in (physical, cpu, hybrid))
    source_checks = {name: {path: sha(ROOT / path) == expected
                           for path, expected in report['metadata']['source_sha256'].items()}
                     for name, report in reports.items() if 'metadata' in report}
    checks['all_current_sources_match'] = all(all(items.values()) for items in source_checks.values())
    artifacts = {'model_sha256': 'research/export/citrinet-256-ls/model.onnx',
                 'tokenizer_sha256': 'research/export/citrinet-256-ls/vocab.txt',
                 'frontend_constants_sha256': 'research/export/citrinet-256-ls/frontend.npz',
                 'checkpoint_sha256': 'research/checkpoints/citrinet-256-ls/stt_en_citrinet_256_ls.nemo'}
    checks['current_artifact_hashes_match'] = all(
        report['metadata'][key] == sha(ROOT / path)
        for report in (physical, cpu, hybrid) for key, path in artifacts.items())
    checks['audio_hash_matches_current_reference'] = (
        physical['audio_sha256'] == sha(ROOT / 'research/reference_speech.wav'))
    timings = {}
    for name, report in (('cpu', cpu), ('hybrid', hybrid)):
        runs = report['runs']
        totals = [run['total_seconds'] for run in runs]
        timing_keys = ('load_seconds', 'frontend_seconds', 'inference_seconds', 'decode_seconds')
        checks[name + '_20_runs_3_warmups'] = len(runs) == 20 and report['warmups'] == 3
        checks[name + '_timings_finite_positive'] = all(
            math.isfinite(run[key]) and run[key] > 0 for run in runs for key in timing_keys + ('total_seconds',))
        checks[name + '_stage_sum_equals_total'] = all(
            abs(sum(run[key] for key in timing_keys) - run['total_seconds']) < 1e-10 for run in runs)
        checks[name + '_percentiles_reproduce'] = all(
            abs(percentile(totals, q) - report['p' + str(q) + '_seconds']) < 1e-10 for q in (50, 95))
        checks[name + '_transcripts_and_lengths_match_physical'] = all(
            run['transcript'] == physical['cpu_transcript'] and run['encoded_length'] == physical['encoded_lengths'][0]
            for run in runs)
        timings[name] = {'p50_seconds': percentile(totals, 50), 'p95_seconds': percentile(totals, 95),
                         'stage_p50_seconds': {key: statistics.median(run[key] for run in runs) for key in timing_keys}}
    counter_keys = ('loads', 'runs', 'ioctls', 'tx_bytes', 'rx_bytes')
    checks['hybrid_positive_dma_each_run'] = all(
        run['hardware_execution'] is True and all(run['dma'][key] > 0 for key in counter_keys)
        for run in hybrid['runs'])
    checks['hybrid_counter_counts_match_parity'] = all(
        run['dma'][key] == physical['dma'][key] for run in hybrid['runs'] for key in counter_keys)
    checks['hybrid_physical_proof_bound'] = hybrid['metadata']['physical_quantized_graph_parity_validated'] is True
    phase_keys = ('ioctl_seconds', 'load_pack_seconds', 'scan_seconds', 'run_pack_seconds', 'unpack_seconds')
    phase_medians = {key: statistics.median(run['dma'][key] for run in hybrid['runs']) for key in phase_keys}
    region_medians = {kind: statistics.median(
        sum(region['seconds'] for region in run['partition_profile'] if region['kind'] == kind)
        for run in hybrid['runs']) for kind in ('cpu', 'fpga')}
    result = {'checks': checks, 'all_integrity_checks_passed': all(checks.values()),
              'report_sha256': {name: sha(path) for name, path in paths.items()},
              'source_checks': source_checks, 'timings': timings,
              'hybrid_dma_counts_each_run': {key: hybrid['runs'][0]['dma'][key] for key in counter_keys},
              'native_phase_p50_seconds': phase_medians, 'partition_p50_seconds': region_medians,
              'hybrid_cpu_p50_ratio': timings['hybrid']['p50_seconds'] / timings['cpu']['p50_seconds'],
              'target_p50_seconds': .8 * timings['cpu']['p50_seconds'],
              'speed_target_passed': timings['hybrid']['p50_seconds'] <= .8 * timings['cpu']['p50_seconds']
                  and timings['hybrid']['p95_seconds'] <= .8 * timings['cpu']['p95_seconds'],
              'limitations': ['Reports are user-supplied; board execution was not independently observed.',
                  'Board-built native binary hash is consistent across reports, but that exact binary was not supplied.',
                  'Reports do not bind the loaded firmware/driver or board clock/temperature telemetry.',
                  'CPU and hybrid timing reports are sequential, not interleaved paired measurements.',
                  'Timed runs lack individual audio hashes; transcript, duration and encoded length are consistent with the parity clip.',
                  'One clip does not establish held-out corpus WER or sustained microphone capture.',
                  'DMA runs count 16-time-frame RUN protocol packets, not ioctl calls.',
                  'Partition/native medians are independently aggregated; sums need not equal total p50.']}
    output = ROOT / 'verification/experiment_board_audit.json'
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'source_checks'}, indent=2))

if __name__ == '__main__':
    main()
