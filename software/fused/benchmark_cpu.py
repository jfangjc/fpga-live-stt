"""Paired complete-processing CPU candidate comparison; no FPGA speed claim.

Run different thread settings in separate processes. Two resident sessions use
non-spinning workers, explicitly recorded, to avoid idle comparator contention.
"""
import argparse
import json
from pathlib import Path
import random
import time
from collections import Counter
import numpy as np
import onnx
import onnxruntime as ort
from common import (ROOT, Frontend, read_audio, decode, errors, environment, sha, corpus,
                    identity, sources, write_json)
from experiment import load_calibration, qdq_model


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-dir', type=Path, default=ROOT/'research/export/citrinet-256-ls')
    p.add_argument('--calibration', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--candidate', choices=('fp32', 'qdq', 'int8'), default='qdq')
    p.add_argument('--candidate-model', type=Path)
    p.add_argument('--baseline-threads', type=int, default=4)
    p.add_argument('--candidate-threads', type=int, default=4)
    p.add_argument('--warmups', type=int, default=3)
    p.add_argument('--repeats', type=int, default=20)
    p.add_argument('--seed', type=int, default=2701)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    if min(args.baseline_threads, args.candidate_threads, args.repeats) < 1 or args.warmups < 0:
        p.error('Invalid threads/repeats/warmups')
    cal = load_calibration(args)
    records = corpus(args.manifest, ('evaluation', 'test'))
    if set(cal['audio_sha256']) & {r['audio_sha256'] for r in records} or set(cal['ids']) & {r['id'] for r in records}:
        raise ValueError('Calibration/evaluation overlap')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    model = onnx.shape_inference.infer_shapes(onnx.load(str(args.model_dir/'model.onnx')))
    candidate_model = qdq_model(model, cal['scales']) if args.candidate == 'qdq' else model
    candidate_artifact_sha256 = None
    if args.candidate == 'int8':
        if not args.candidate_model:
            p.error('--candidate-model is required for INT8')
        proof = json.loads(args.candidate_model.with_suffix('.json').read_text())
        candidate_artifact_sha256 = sha(args.candidate_model)
        if proof['source_identity'] != identity(args.model_dir) or proof['model_sha256'] != candidate_artifact_sha256:
            raise ValueError('INT8 candidate identity mismatch')
        if (set(proof['calibration_audio_sha256']) & {r['audio_sha256'] for r in records}
                or set(proof['calibration_ids']) & {r['id'] for r in records}):
            raise ValueError('INT8 calibration/evaluation overlap')
        candidate_model = onnx.load(str(args.candidate_model))
    runners = {}
    initialization = {}
    optimized_ops = {}
    for name, graph, threads in (('baseline', model, args.baseline_threads),
                                  ('candidate', candidate_model, args.candidate_threads)):
        opt = ort.SessionOptions()
        opt.intra_op_num_threads = threads; opt.inter_op_num_threads = 1
        opt.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opt.add_session_config_entry('session.intra_op.allow_spinning', '0')
        opt.add_session_config_entry('session.inter_op.allow_spinning', '0')
        optimized = args.out.parent/(args.out.stem+'-'+name+'-optimized.onnx')
        opt.optimized_model_filepath = str(optimized)
        start = time.perf_counter()
        runners[name] = ort.InferenceSession(graph.SerializeToString(), opt, providers=['CPUExecutionProvider'])
        initialization[name] = time.perf_counter()-start
        optimized_ops[name] = dict(Counter(n.domain+'::'+n.op_type for n in onnx.load(str(optimized)).graph.node))
    frontend = Frontend(args.model_dir)
    vocab = (args.model_dir/'vocab.txt').read_text().splitlines()

    def call(name, path):
        before = environment()
        start = time.perf_counter()
        audio = read_audio(path); features, lengths = frontend(audio)
        logits, encoded = runners[name].run(None, {'features': features, 'feature_lengths': lengths})
        transcript = decode(logits[0], encoded[0], vocab)
        seconds = time.perf_counter()-start
        if not np.all(np.isfinite(logits)):
            raise ValueError('Nonfinite output')
        return {'seconds': seconds, 'transcript': transcript, 'encoded_length': int(encoded[0]),
                'before': before, 'after': environment()}

    rows = []
    rng = random.Random(args.seed)
    for record in records:
        for _ in range(args.warmups):
            for name in runners:
                call(name, record['path'])
        for repeat in range(args.repeats):
            order = ['baseline', 'candidate']; rng.shuffle(order)
            pair = {name: call(name, record['path']) for name in order}
            if pair['baseline']['encoded_length'] != pair['candidate']['encoded_length']:
                raise ValueError('Encoded length mismatch')
            rows.append({'id': record['id'], 'repeat': repeat, 'order': order, 'results': pair})
        print(record['id'], 'paired runs', args.repeats, flush=True)
    summary = {}
    word_errors = {'baseline': 0, 'candidate': 0}
    words_total = 0
    per_clip = []
    for record in records:
        selected = [r for r in rows if r['id'] == record['id']]
        clip = {'id': record['id'], 'audio_sha256': record['audio_sha256']}
        for name in runners:
            transcripts = {r['results'][name]['transcript'] for r in selected}
            if len(transcripts) != 1:
                raise ValueError('Nondeterministic transcripts')
            transcript = next(iter(transcripts))
            count, words = errors(record.get('text', record.get('reference')), transcript)
            if words == 0:
                raise ValueError('Empty reference')
            word_errors[name] += count
            clip[name+'_text'] = transcript
            clip[name+'_p50'] = float(np.percentile([r['results'][name]['seconds'] for r in selected], 50))
            clip[name+'_p95'] = float(np.percentile([r['results'][name]['seconds'] for r in selected], 95))
        words_total += words
        per_clip.append(clip)
    for name in runners:
        times = [r['results'][name]['seconds'] for r in rows]
        summary[name] = {'global_p50': float(np.percentile(times, 50)),
                         'global_p95': float(np.percentile(times, 95)), 'wer': word_errors[name]/words_total}
    summary['aggregate_clip_median_reduction'] = 1-sum(r['candidate_p50'] for r in per_clip)/sum(r['baseline_p50'] for r in per_clip)
    report = {'purpose': 'CPU baseline screening; category-complete reviewed WER is still required',
              'hardware_execution': False, 'model_identity': identity(args.model_dir),
              'sources_sha256': sources(), 'manifest_sha256': sha(args.manifest),
              'calibration_sha256': sha(args.calibration), 'candidate': args.candidate,
              'candidate_artifact_sha256': candidate_artifact_sha256,
              'baseline_threads': args.baseline_threads, 'candidate_threads': args.candidate_threads,
              'worker_spinning': False, 'warmups': args.warmups, 'repeats': args.repeats,
              'initialization_seconds': initialization, 'optimized_operator_counts': optimized_ops,
              'candidate_int8_conv_kernels_present': any('QLinearConv' in name or 'ConvInteger' in name
                                                         for name in optimized_ops['candidate']),
              'summary': summary, 'clips': per_clip, 'paired_runs': rows,
              'final_accuracy_gate_claimed': False,
              'limits': ['Global percentiles mix clip lengths; select using per-clip paired timings.',
                         'QDQ naming alone does not prove CPU INT8 kernels; optimized operator counts are recorded.',
                         'This script executes no accelerator requests and proves no FPGA speedup.']}
    write_json(args.out, report)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
