"""Evaluate paired same-model KV260 warm timings and corpus WER.

Input JSON contract: metadata plus rows [{id,reference,cpu_text,fpga_text,
cpu_seconds:[...],fpga_seconds:[...]}]. Timings must include full processing.
No board or accuracy success is inferred when evidence is missing.
"""
import argparse
import json
import math
import re
import unicodedata
from pathlib import Path


def words(text):
    # Exact normalization contract used by software/evaluation/benchmark.py.
    text = unicodedata.normalize('NFKC', text).lower()
    return re.sub(r"[^\w\s']", ' ', text).split()


def edits(reference, hypothesis):
    a, b = words(reference), words(hypothesis)
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        out = [i]
        for j, y in enumerate(b, 1):
            out.append(min(out[-1] + 1, row[j] + 1, row[j-1] + (x != y)))
        row = out
    return row[-1], len(a)


def percentile(values, p):
    values = sorted(values)
    index = (len(values) - 1) * p
    lo, hi = math.floor(index), math.ceil(index)
    return values[lo] + (values[hi] - values[lo]) * (index - lo)


def evaluate(data):
    meta, rows = data['metadata'], data['rows']
    required = ['board', 'model_sha256', 'audio_manifest_sha256',
                'preprocessing_sha256', 'decoder_sha256', 'cpu_threads',
                'cpu_precision', 'fpga_precision', 'clock_hz',
                'thermal_before_c', 'thermal_after_c', 'initialization_seconds',
                'calibration_ids', 'evaluation_ids', 'full_processing_timing',
                'warm_state_resident', 'capture_newly_dropped_samples',
                'cpu_optimized', 'physical_fpga_execution', 'evaluation_categories',
                'tokenizer_sha256', 'source_provenance_sha256',
                'original_model_parity_report_sha256', 'physical_quantized_graph_parity_report_sha256',
                'physical_quantized_graph_parity_validated', 'capture_software_dropped_samples',
                'reference_transcripts_reviewed', 'reference_transcripts_sha256']
    missing = [k for k in required if k not in meta or meta[k] is None]
    if missing:
        raise ValueError('Missing evidence: ' + ', '.join(missing))
    if meta['board'] != 'KV260' or meta['cpu_threads'] < 1:
        raise ValueError('KV260 and explicit positive CPU thread count required')
    if not all(meta[k] is True for k in ['full_processing_timing', 'warm_state_resident', 'cpu_optimized', 'physical_fpga_execution']):
        raise ValueError('Physical optimized warm full-processing evidence required')
    if not (meta.get('complete_original_nemo_wrapper_validated') is True or
            meta.get('original_model_output_parity_validated') is True):
        raise ValueError('Complete original-model output parity is required; component/export parity is insufficient')
    if meta['physical_quantized_graph_parity_validated'] is not True:
        raise ValueError('Physical quantized graph parity required')
    if meta['reference_transcripts_reviewed'] is not True:
        raise ValueError('Reference transcripts must be reviewed')
    hash_fields=['model_sha256','tokenizer_sha256','audio_manifest_sha256',
                 'preprocessing_sha256','decoder_sha256','original_model_parity_report_sha256',
                 'physical_quantized_graph_parity_report_sha256','reference_transcripts_sha256']
    for field in hash_fields:
        if not isinstance(meta[field],str) or not re.fullmatch(r'[0-9a-fA-F]{64}',meta[field]):
            raise ValueError('Valid SHA256 provenance required: '+field)
    if not isinstance(meta['source_provenance_sha256'],dict) or not meta['source_provenance_sha256']:
        raise ValueError('Nonempty source provenance hash mapping required')
    for path,value in meta['source_provenance_sha256'].items():
        if not path or not isinstance(value,str) or not re.fullmatch(r'[0-9a-fA-F]{64}',value):
            raise ValueError('Invalid source provenance hash: '+str(path))
    for field in ['clock_hz','thermal_before_c','thermal_after_c']:
        value=meta[field]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or (field=='clock_hz' and value<=0):
            raise ValueError('Finite measured clock/temperature required: '+field)
    for field in ['capture_newly_dropped_samples','capture_software_dropped_samples']:
        if type(meta[field]) is not int or meta[field]<0:
            raise ValueError('Nonnegative integer capture counter required: '+field)
    categories = {'quiet', 'accented', 'numbers', 'names', 'noise'}
    if not categories.issubset(set(meta['evaluation_categories'])):
        raise ValueError('Evaluation must cover quiet, accented, numbers, names, noise')
    if set(meta['calibration_ids']) & set(meta['evaluation_ids']):
        raise ValueError('Calibration/evaluation overlap')
    if not rows or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Rows must be nonempty with unique recording IDs')
    if set(r['id'] for r in rows) != set(meta['evaluation_ids']):
        raise ValueError('Rows must match held-out evaluation manifest')
    cpu, fpga = [], []
    cpu_edits = fpga_edits = ref_words = 0
    for r in rows:
        a, b = r['cpu_seconds'], r['fpga_seconds']
        if len(a) < 10 or len(a) != len(b) or any(not math.isfinite(v) or v <= 0 for v in a+b):
            raise ValueError('At least 10 paired finite positive warm samples per clip required')
        cpu.extend(a); fpga.extend(b)
        e, n = edits(r['reference'], r['cpu_text'])
        if n==0:
            raise ValueError('Each speech evaluation clip requires a nonempty reviewed reference')
        f, _ = edits(r['reference'], r['fpga_text'])
        cpu_edits += e; fpga_edits += f; ref_words += n
    if ref_words == 0:
        raise ValueError('Nonempty reference transcripts required')
    a, b = percentile(cpu, .5), percentile(fpga, .5)
    c, d = percentile(cpu, .95), percentile(fpga, .95)
    cpu_wer, fpga_wer = cpu_edits/ref_words, fpga_edits/ref_words
    speed = b <= .8*a and d <= .8*c
    accuracy = fpga_wer - cpu_wer <= .01 + 1e-12
    capture = meta['capture_newly_dropped_samples'] == 0 and meta['capture_software_dropped_samples'] == 0
    return dict(passed=speed and accuracy and capture, timing_gate=speed,
                accuracy_gate=accuracy, capture_gate=capture,
                cpu_p50_seconds=a, fpga_p50_seconds=b,
                cpu_p95_seconds=c, fpga_p95_seconds=d,
                p50_time_reduction_percent=100*(1-b/a),
                cpu_wer=cpu_wer, fpga_wer=fpga_wer,
                absolute_wer_degradation_percentage_points=100*(fpga_wer-cpu_wer),
                fpga_p50_vs_historical_quartznet_1_9651=b/1.9651,
                reference_word_count=ref_words, recordings=len(rows),
                samples_per_backend=len(cpu),
                normalization='Unicode NFKC, lowercase, punctuation-to-space, whitespace tokenization, preserve apostrophes; identical to benchmark.py',
                methodology='Micro-averaged corpus WER; pooled clip warm latency p50/p95; both percentile timing gates enforced')


def from_benchmark(report, evidence):
    """Convert runner output; require separately collected provenance/capture evidence."""
    if report.get('measured_on_physical_board') is not True:
        raise ValueError('Physical board report required')
    cm, fm = report['metadata']['cpu'], report['metadata']['fpga']
    for field in ('model_sha256', 'tokenizer_sha256', 'preprocessing_id', 'decoder_id'):
        if not cm.get(field) or cm[field] != fm.get(field):
            raise ValueError('Paired runner identity mismatch: ' + field)
    meta = dict(evidence)
    # Hashes for frontend/decoder, calibration IDs and capture/thermal evidence
    # remain required in the sidecar; runner IDs are not silently called hashes.
    for field in ['complete_original_nemo_wrapper_validated','original_model_output_parity_validated',
                  'physical_quantized_graph_parity_validated']:
        # A runner's explicit failed validation cannot be overridden by sidecar.
        if fm.get(field) is False or (field!='physical_quantized_graph_parity_validated' and cm.get(field) is False):
            meta[field]=False
    if cm.get('original_nemo_wrapper_validated') is False or fm.get('original_nemo_wrapper_validated') is False:
        meta['complete_original_nemo_wrapper_validated']=False
        meta['original_model_output_parity_validated']=False
    meta.update(model_sha256=cm['model_sha256'],tokenizer_sha256=cm['tokenizer_sha256'],
                audio_manifest_sha256=report['manifest_sha256'],
                cpu_threads=cm['threads'], cpu_precision=cm['precision'],
                fpga_precision=fm['precision'], clock_hz=report['pl_clock_hz'],
                initialization_seconds=report['initialization_seconds'],
                evaluation_ids=[r['id'] for r in report['corpus']],
                physical_fpga_execution=fm.get('hardware_execution') is True,
                evaluation_categories=list({('accented' if c == 'accent' else c)
                    for r in report['corpus'] for c in r['categories']}))
    rows = []
    for record in report['corpus']:
        row = dict(id=record['id'], reference=record['text'])
        for mode in ('cpu', 'fpga'):
            selected = sorted((s for s in report['samples'] if s['id'] == record['id'] and s['mode'] == mode), key=lambda s:s['repeat'])
            if not selected or len({s['transcript'] for s in selected}) != 1:
                raise ValueError('Transcript instability across warm repeats requires inspection')
            row[mode+'_text'] = selected[0]['transcript']
            row[mode+'_seconds'] = [s['total_seconds'] for s in selected]
        rows.append(row)
    return dict(metadata=meta, rows=rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--benchmark-evidence', type=Path,
                        help='Required provenance/capture sidecar when INPUT is benchmark.py output')
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text())
        if args.benchmark_evidence:
            data = from_benchmark(data, json.loads(args.benchmark_evidence.read_text()))
        result = evaluate(data)
    except (ValueError, KeyError, TypeError) as e:
        parser.exit(2, 'Evidence rejected: ' + str(e) + '\n')
    text = json.dumps(result, indent=2) + '\n'
    print(text, end='')
    if args.output:
        args.output.write_text(text)
    raise SystemExit(0 if result['passed'] else 1)
