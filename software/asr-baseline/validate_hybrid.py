#!/usr/bin/env python3
"""Host-only graph correctness and experimental dynamic INT8 comparison."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import time

import numpy as np
import onnx
import onnxruntime as ort
from onnx import helper
from quartznet_cpu import frontend, read_pcm24, decode
from quartznet_hybrid import Graph, vocabulary
from qn_tile import pointwise, MAGIC


def emulate_packet(data):
    magic, k, reserved0, reserved1 = struct.unpack_from('<IIII', data)
    if magic != MAGIC or reserved0 or reserved1 or len(data) != 16+32*k:
        raise ValueError('Malformed emulated packet')
    x = np.frombuffer(data, dtype=np.int8, count=16*k, offset=16).reshape(k,16)
    w = np.frombuffer(data, dtype=np.int8, count=16*k, offset=16+16*k).reshape(k,16)
    return (x.astype(np.int32).T @ w.astype(np.int32)).astype('<i4').tobytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wav', type=Path)
    parser.add_argument('--model', type=Path, default=Path(__file__).parent/'model')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    rng = np.random.default_rng(72)
    x = rng.integers(-127,128,(1025,19),dtype=np.int16).astype(np.int8)
    w = rng.integers(-127,128,(21,1025),dtype=np.int16).astype(np.int8)
    assert np.array_equal(pointwise(x,w,emulate_packet), w.astype(np.int32)@x.astype(np.int32))
    audio = read_pcm24(args.wav)
    features, valid = frontend(audio)
    features = features[:,:,:valid].copy()
    vocab = vocabulary(args.model)
    model_path = args.model/'model.onnx'
    model = onnx.load(str(model_path))
    # Observe each Conv against ORT, from the earliest layers to final logits.
    names = [n.output[0] for n in model.graph.node if n.op_type == 'Conv']
    original_outputs = {o.name for o in model.graph.output}
    model.graph.output.extend(helper.make_tensor_value_info(name, onnx.TensorProto.FLOAT, None)
                              for name in names if name not in original_outputs)
    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    baseline_session = ort.InferenceSession(str(model_path), options, providers=['CPUExecutionProvider'])
    started = time.perf_counter()
    baseline_output = baseline_session.run(['logprobs'], {'audio_signal':features})[0]
    baseline_seconds = time.perf_counter()-started
    session = ort.InferenceSession(model.SerializeToString(), options, providers=['CPUExecutionProvider'])
    names = ['logprobs']+names
    started = time.perf_counter()
    reference = dict(zip(names, session.run(names, {'audio_signal':features})))
    ort_seconds = time.perf_counter()-started
    layer_checks = []
    def compare(node, value):
        if node.output[0] in reference:
            expected = reference[node.output[0]]
            assert value.shape == expected.shape, node.name
            layer_checks.append({'name':node.name, 'shape':list(value.shape),
                                 'max_abs_error':float(np.max(np.abs(value-expected))),
                                 'mean_abs_error':float(np.mean(np.abs(value-expected)))})
    graph = Graph(model_path,'fp32')
    started = time.perf_counter()
    fp32 = graph.run(features,compare)
    fp32_seconds = time.perf_counter()-started
    fp32_layers = graph.stats
    observed_output_error = float(np.max(np.abs(reference['logprobs']-baseline_output)))
    original = baseline_output
    reference.clear()
    hybrid = Graph(model_path,'emulate')
    started = time.perf_counter()
    int8 = hybrid.run(features)
    hybrid_seconds = time.perf_counter()-started
    encoder_frames = (valid+1)//2
    ort_text = decode(original,vocab,encoder_frames)
    fp32_text = decode(fp32,vocab,encoder_frames)
    int8_text = decode(int8,vocab,encoder_frames)
    report = {
        'experimental':True, 'hardware_execution':False, 'accuracy_validated':False,
        'calibration_corpus':None, 'wav':str(args.wav.resolve()),
        'model_sha256':hashlib.sha256(model_path.read_bytes()).hexdigest(),
        'audio_seconds':len(audio)/16000, 'valid_feature_frames':valid,
        'output_shape':list(original.shape), 'topology':dict(Counter(n.op_type for n in model.graph.node)),
        'tile_packet_int32_check':'exact, including K=1025 split and T/O tails',
        'ort_observed_graph_seconds':ort_seconds,
        'ort_cpu_baseline_seconds':baseline_seconds,
        'ort_observed_vs_baseline_max_abs_error':observed_output_error,
        'fp32_numpy_seconds':fp32_seconds, 'hybrid_cpu_emulation_seconds':hybrid_seconds,
        'fp32_logprobs_max_abs_error':float(np.max(np.abs(fp32-original))),
        'fp32_argmax_agreement':float(np.mean(np.argmax(fp32,-1)==np.argmax(original,-1))),
        'hybrid_logprobs_max_abs_error':float(np.max(np.abs(int8-original))),
        'hybrid_argmax_agreement':float(np.mean(np.argmax(int8,-1)==np.argmax(original,-1))),
        'ort_transcript':ort_text, 'fp32_numpy_transcript':fp32_text,
        'hybrid_cpu_emulation_transcript':int8_text,
        'estimated_tile_transactions':sum(n.get('tile_transactions',0) for n in hybrid.stats),
        'fp32_layer_checks':layer_checks, 'fp32_layer_timings':fp32_layers,
        'hybrid_layer_timings':hybrid.stats,
        'timing_note':'Host wall-clock only; FP32 NumPy includes layer comparisons, observed ORT graph exposes all Conv outputs. Separate ORT baseline uses the original graph. NumPy BLAS threading is environment-dependent. No DMA or FPGA timing.'
    }
    args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if not k.endswith('checks') and not k.endswith('timings')},indent=2))
    if report['fp32_logprobs_max_abs_error'] > 0.02 or fp32_text != ort_text:
        raise SystemExit('FP32 graph validation failed: inspect saved layer checks')


if __name__ == '__main__':
    main()
