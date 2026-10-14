"""Independent integrity and percentile audit of CPU fallback diagnostics.

This reads supplied board evidence; it does not execute board measurements.
Uses only the standard library, independently of NumPy percentile code.
"""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METRICS = ('full_cpu_graph_seconds', 'partition_seconds',
           'cpu_region_seconds', 'fp32_pointwise_seconds')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values, q):
    values = sorted(values)
    index = (len(values) - 1) * q / 100
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def main():
    checks, timings, sources, report_hashes = {}, {}, {}, {}
    audio_hash = sha(ROOT / 'research/reference_speech.wav')
    model_hash = sha(ROOT / 'research/export/citrinet-256-ls/model.onnx')
    transcripts = []
    for label, pool, threads in (('per1', 'per-session', 1), ('shared1', 'shared', 1),
                                 ('shared2', 'shared', 2), ('shared4', 'shared', 4)):
        path = ROOT / 'reports' / ('regions-' + label + '-board.json')
        report = json.loads(path.read_text())
        report_hashes[label] = sha(path)
        rows = report['runs']
        local = {
            'expected_configuration': report['pool'] == pool and report['threads'] == threads,
            '20_runs_3_warmups': len(rows) == 20 and report['warmups'] == 3,
            'fp32_parity_reported': report['fp32_output_parity_passed'] is True,
            'cpu_only_explicit': report['hardware_execution'] is False,
            'audio_matches': report['wav_sha256'] == audio_hash,
            'model_matches': report['model_sha256'] == model_hash,
            'thread_environment_recorded': report['thread_environment'] == {
                'OMP_NUM_THREADS': '4', 'OPENBLAS_NUM_THREADS': '4', 'MKL_NUM_THREADS': '4'},
            'finite_positive_timing': all(math.isfinite(row[key]) and row[key] > 0
                                          for row in rows for key in METRICS),
            '253_alternating_steps': all(len(row['partition_profile']) == 253 and
                all(step['kind'] == ('cpu' if i % 2 == 0 else 'fpga')
                    for i, step in enumerate(row['partition_profile'])) for row in rows),
            'finite_nonnegative_step_timing': all(math.isfinite(step['seconds']) and step['seconds'] >= 0
                                                  for row in rows for step in row['partition_profile']),
            'cpu_sum_reproduces': all(abs(sum(step['seconds'] for step in row['partition_profile']
                if step['kind'] == 'cpu') - row['cpu_region_seconds']) < 1e-10 for row in rows),
            'pointwise_sum_reproduces': all(abs(sum(step['seconds'] for step in row['partition_profile']
                if step['kind'] == 'fpga') - row['fp32_pointwise_seconds']) < 1e-10 for row in rows),
            'partition_bounds_profile_sum': all(row['partition_seconds'] >=
                row['cpu_region_seconds'] + row['fp32_pointwise_seconds'] for row in rows),
            'percentiles_reproduce': all(abs(percentile([row[key] for row in rows], q) -
                report[key + '_p' + str(q)]) < 1e-10 for key in METRICS for q in (50, 95)),
        }
        sources[label] = {relative: sha(ROOT / relative) == expected
                          for relative, expected in report['sources_sha256'].items()}
        local['all_current_sources_match'] = all(sources[label].values())
        checks[label] = local
        transcripts.append(report['transcript'])
        timings[label] = {key: {'p50': percentile([row[key] for row in rows], 50),
                               'p95': percentile([row[key] for row in rows], 95)} for key in METRICS}
        timings[label]['unprofiled_partition_overhead_seconds'] = {
            'p50': percentile([row['partition_seconds'] - row['cpu_region_seconds'] -
                              row['fp32_pointwise_seconds'] for row in rows], 50),
            'p95': percentile([row['partition_seconds'] - row['cpu_region_seconds'] -
                              row['fp32_pointwise_seconds'] for row in rows], 95)}
    checks['transcripts_match_across_configurations'] = len(set(transcripts)) == 1
    valid = all(all(value.values()) if isinstance(value, dict) else value for value in checks.values())
    baseline = timings['per1']['cpu_region_seconds']['p50']
    result = {
        'complete': valid,
        'scope': 'Integrity of supplied CPU-only diagnosis; no independently executed board run or speedup claim',
        'checks': checks, 'source_checks': sources, 'report_sha256': report_hashes,
        'timings_seconds': timings,
        'fallback_p50_improvement_percent_vs_per1': {
            label: 100 * (1 - values['cpu_region_seconds']['p50'] / baseline)
            for label, values in timings.items()},
        'production_recommendation': 'Retain the measured production configuration until a physical hybrid run validates shared2. Shared2 is a candidate because fallback median improves 9.11%; its FP32 pointwise contention penalty may differ in the native FPGA path. Reject shared4 on this evidence.',
        'caveats': [
            'FPGA-labelled pointwise steps execute FP32 NumPy BLAS in this diagnostic; they are not FPGA timings.',
            'The full-graph CPU comparator uses the selected 1/2/4 ORT threads, so it differs across configurations.',
            'BLAS environment is 4 threads for every configuration; shared ORT workers may contend with BLAS. Worker spinning is requested off but not established.',
            'FP32 fallback inputs differ from the production dynamic INT8 path. Only a physical hybrid test can establish production timing.',
            'Reported output parity is an assertion result bound to current profiler source, not a retained raw logit tensor comparison.',
            'Profiler does not record thermals/clocks/affinity or realized BLAS thread count; causal attribution to contention requires further evidence.',
            'Partition and full-graph inference timings omit WAV loading, frontend and CTC decode; they are not end-to-end acceptance measurements.'
        ]}
    output = ROOT / 'verification/fallback_board_audit.json'
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'complete': valid, 'timings_seconds': timings,
                      'fallback_p50_improvement_percent_vs_per1': result['fallback_p50_improvement_percent_vs_per1']}, indent=2))
    if not valid:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
