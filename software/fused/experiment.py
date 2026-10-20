"""Profile real Citrinet blocks, calibrate held-out INT8, and evaluate candidates.

All generated results explicitly distinguish host diagnostics from KV260 proof.
Existing tested runtime, firmware and deployment archives are never overwritten.
"""
import argparse
import copy
import json
from pathlib import Path
import platform
import time
import numpy as np
import onnx
from onnx import helper, numpy_helper
from common import (ROOT, Frontend, read_audio, decode, errors, environment, sha,
                    session, corpus, calibration_tensors, expose, blocks, block_id,
                    write_json, identity, sources)
from oracle import evaluator, quantize, conv_parameters, conv1d, requantize, requant_parameters


def load_model(args):
    return onnx.shape_inference.infer_shapes(onnx.load(str(args.model_dir / 'model.onnx')))


def feed(frontend, path):
    features, lengths = frontend(read_audio(path))
    return {'features': features, 'feature_lengths': lengths}


def profile(args):
    model = load_model(args)
    if hasattr(captured_session_model_shape, 'cache'):
        del captured_session_model_shape.cache
    inventory = blocks(model)
    args.out.mkdir(parents=True, exist_ok=True)
    opt = session(model, args.threads, args.out / 'ort')
    inputs = feed(Frontend(args.model_dir), args.wav)
    for _ in range(args.warmups):
        opt.run(None, inputs)
    times = []
    before = environment()
    for _ in range(args.runs):
        start = time.perf_counter(); opt.run(None, inputs)
        times.append(time.perf_counter() - start)
    after = environment()
    path = Path(opt.end_profiling())
    events = json.loads(path.read_text())
    intervals = [e for e in events if e.get('name') == 'model_run'][-args.runs:]
    measured = [e for e in events if e.get('cat') == 'Node' and e.get('name', '').endswith('_kernel_time')
                and any(r['ts'] <= e['ts'] < r['ts'] + r['dur'] for r in intervals)]
    boundary_names = sorted({v for b in inventory for v in b['inputs'] + b['outputs']})
    captured_session = session(expose(model, boundary_names), args.threads)
    captured = dict(zip([v.name for v in captured_session.get_outputs()], captured_session.run(None, inputs)))
    captured.update(inputs)
    arrays = {v.name: numpy_helper.to_array(v) for v in model.graph.initializer}
    for b in inventory:
        kernels = [e for e in measured if block_id(e['name']) == b['id']]
        b['profile_kernel_seconds_per_run'] = sum(e['dur'] for e in kernels) / 1e6 / args.runs
        b['boundary_shapes'] = {n: list(captured[n].shape) for n in b['inputs'] + b['outputs']}
        b['boundary_fp32_bytes'] = sum(captured[n].nbytes for n in b['inputs'] + b['outputs'])
        b['boundary_int8_payload_bytes'] = sum(captured[n].size if captured[n].dtype == np.float32
                                                else captured[n].nbytes for n in b['inputs'] + b['outputs'])
        subset = [n for n in model.graph.node if block_id(n.name) == b['id']]
        weights = {n.input[1] for n in subset if n.op_type == 'Conv'}
        b['conv_int8_weights_bytes'] = sum(arrays[n].size for n in weights)
        b['conv_macs'] = sum(int(captured_session_model_shape(model, n, captured, arrays)) for n in subset if n.op_type == 'Conv')
        b['ideal_256_mac_100mhz_seconds'] = b['conv_macs'] / 256 / 100_000_000
    ranked = sorted(inventory, key=lambda b: b['profile_kernel_seconds_per_run'], reverse=True)
    # Rank only representative repeated-convolution blocks with actual global SE.
    representative = [b for b in ranked if b['convolutions'] >= 10 and b['global_se']]
    selected = representative[0]
    from onnx.utils import Extractor
    extracted = Extractor(model).extract_model(selected['inputs'], selected['outputs'])
    onnx.checker.check_model(extracted)
    onnx.save(extracted, str(args.out / 'selected_block.onnx'))
    np.savez(args.out / 'selected_block_inputs.npz', **{n: captured[n] for n in selected['inputs']})
    block_session = session(extracted, args.threads)
    block_feed = {n: captured[n] for n in selected['inputs']}
    actual = block_session.run(None, block_feed)
    for name, value in zip(selected['outputs'], actual):
        if value.dtype.kind == 'f':
            np.testing.assert_allclose(value, captured[name], atol=1e-3, rtol=1e-4)
        else:
            np.testing.assert_array_equal(value, captured[name])
    block_times = []
    for _ in range(args.warmups):
        block_session.run(None, block_feed)
    for _ in range(args.runs):
        start = time.perf_counter(); block_session.run(None, block_feed)
        block_times.append(time.perf_counter() - start)
    report = {'purpose': 'CPU operator attribution and block extraction; no physical FPGA execution',
              'hardware_execution': False, 'environment_before': before, 'environment_after': after,
              'model_identity': identity(args.model_dir), 'sources_sha256': sources(),
              'audio_sha256': sha(args.wav), 'threads': args.threads,
              'warmups': args.warmups, 'runs': args.runs, 'inference_seconds': times,
              'inference_p50': float(np.percentile(times, 50)), 'inference_p95': float(np.percentile(times, 95)),
              'profiling_overhead_included': True, 'blocks': ranked,
              'selected_block_id': selected['id'], 'selected_block_parity_passed': True,
              'selected_block_model_sha256': sha(args.out / 'selected_block.onnx'),
              'selected_block_inputs_sha256': sha(args.out / 'selected_block_inputs.npz'),
              'selected_block_cpu_seconds': block_times,
              'selected_block_cpu_p50': float(np.percentile(block_times, 50)),
              'limits': ['Kernel attribution includes instrumentation overhead.',
                         'Block CPU timing excludes frontend and is not whole-model acceptance.',
                         'Ideal MAC time omits DMA, replay, loading and stalls; it is only a lower bound.',
                         'Host rankings must be rerun on KV260 before selecting hardware.']}
    write_json(args.out / 'profile.json', report)
    print(json.dumps({k: report[k] for k in ('selected_block_id', 'selected_block_parity_passed',
                                          'selected_block_cpu_p50', 'inference_p50')}, indent=2))


def captured_session_model_shape(model, node, captured, arrays):
    """Resolve T from the block's input and concrete Conv geometry, no static T guess."""
    # Instrumented forward execution is cached per call, including strided stages.
    if not hasattr(captured_session_model_shape, 'cache'):
        names = [n.output[0] for n in model.graph.node if n.op_type == 'Conv']
        probe = session(expose(model, names), 1)
        values = probe.run(names, {n.name: captured[n.name] for n in model.graph.input})
        captured_session_model_shape.cache = {n: v.shape for n, v in zip(names, values)}
    shape = captured_session_model_shape.cache[node.output[0]]
    weight = arrays[node.input[1]]
    return np.prod(shape) * weight.shape[1] * weight.shape[2]


def calibrate(args):
    model = load_model(args)
    names = calibration_tensors(model)
    records = corpus(args.manifest, ('calibration',))
    runner = session(expose(model, names), args.threads)
    frontend = Frontend(args.model_dir)
    maxima = {name: 0.0 for name in names}
    observed = {}
    for record in records:
        values = runner.run(names, feed(frontend, record['path']))
        for name, value in zip(names, values):
            if not np.all(np.isfinite(value)):
                raise ValueError('Nonfinite calibration activation: ' + name)
            maxima[name] = max(maxima[name], float(np.max(np.abs(value))))
            observed[name] = list(value.shape)
        print('calibrated', record['id'], flush=True)
    report = {'schema': 1, 'method': 'symmetric per-tensor minmax /127; per-output-channel weights',
              'model_identity': identity(args.model_dir), 'sources_sha256': sources(),
              'manifest_sha256': sha(args.manifest),
              'audio_sha256': [r['audio_sha256'] for r in records], 'ids': [r['id'] for r in records],
              'scales': {n: float(np.float32(maxima[n] / 127)) if maxima[n] else 1.0 for n in names},
              'max_abs': maxima, 'last_observed_shapes': observed, 'hardware_execution': False,
              'accuracy_gate_passed': False}
    write_json(args.out, report)


def load_calibration(args):
    data = json.loads(args.calibration.read_text())
    if data['model_identity'] != identity(args.model_dir):
        raise ValueError('Calibration artifact identity mismatch')
    scales = data['scales']
    if any(not np.isfinite(s) or s <= 0 for s in scales.values()):
        raise ValueError('Invalid calibration scale')
    return data


def qdq_model(model, scales, exclude_blocks=()):
    """One-session CPU candidate and FP32/QDQ screening graph, not exact FPGA oracle."""
    result = copy.deepcopy(model)
    initial = {v.name: numpy_helper.to_array(v) for v in result.graph.initializer}
    nodes = []
    replacements = {}
    counter = 0

    def add_array(name, value):
        result.graph.initializer.append(numpy_helper.from_array(np.asarray(value), name))

    def activation(name):
        nonlocal counter
        prefix = '__fused_qdq_' + str(counter); counter += 1
        scale = np.float32(scales[name])
        add_array(prefix + '_s', scale); add_array(prefix + '_z', np.int8(0))
        add_array(prefix + '_min', np.float32(-127 * scale))
        add_array(prefix + '_max', np.float32(127 * scale))
        nodes.extend([helper.make_node('Clip', [name, prefix+'_min', prefix+'_max'], [prefix+'_clip'], name=prefix+'_Clip'),
                      helper.make_node('QuantizeLinear', [prefix+'_clip', prefix+'_s', prefix+'_z'], [prefix+'_q'], name=prefix+'_Q'),
                      helper.make_node('DequantizeLinear', [prefix+'_q', prefix+'_s', prefix+'_z'], [prefix+'_dq'], name=prefix+'_DQ')])
        replacements[name] = prefix + '_dq'

    for info in model.graph.input:
        if info.name in scales:
            activation(info.name)
    for original in model.graph.node:
        node = copy.deepcopy(original)
        for i, name in enumerate(node.input):
            node.input[i] = replacements.get(name, name)
        excluded = block_id(node.name) in exclude_blocks or node.name.startswith('/decoder/')
        if node.op_type == 'Conv' and not excluded:
            weight = initial[original.input[1]]
            sw = np.max(np.abs(weight), axis=(1, 2)).astype(np.float32) / np.float32(127)
            sw[sw == 0] = 1
            prefix = '__fused_weight_' + str(counter); counter += 1
            add_array(prefix+'_q', quantize(weight, sw[:, None, None]))
            add_array(prefix+'_s', sw); add_array(prefix+'_z', np.zeros(len(sw), np.int8))
            nodes.append(helper.make_node('DequantizeLinear', [prefix+'_q', prefix+'_s', prefix+'_z'],
                                          [prefix+'_dq'], axis=0, name=prefix+'_DQ'))
            node.input[1] = prefix+'_dq'
        nodes.append(node)
        if node.output[0] in scales and not excluded:
            activation(node.output[0])
    # Outputs are currently logits/lengths, but handle arbitrary screening graphs.
    for output in result.graph.output:
        output.name = replacements.get(output.name, output.name)
    del result.graph.node[:]; result.graph.node.extend(nodes)
    # Remove unused FP32 weights so deployment size reflects the actual candidate.
    used = {v for n in result.graph.node for v in n.input}
    retained = [v for v in result.graph.initializer if v.name in used]
    del result.graph.initializer[:]; result.graph.initializer.extend(retained)
    onnx.checker.check_model(result)
    return result


def build(args):
    data = load_calibration(args)
    model = qdq_model(load_model(args), data['scales'], args.exclude_blocks)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(args.out))
    write_json(args.out.with_suffix('.json'), {'model_sha256': sha(args.out),
               'source_identity': identity(args.model_dir), 'calibration_sha256': sha(args.calibration),
               'exclude_blocks': args.exclude_blocks, 'sources_sha256': sources(),
               'precision': 'static INT8 QDQ Conv weights/activation; FP32 bias, SE, residual arithmetic',
               'purpose': 'CPU baseline candidate and numerical screen; QDQ is not Q31 oracle parity',
               'hardware_execution': False})


def vectors(args):
    data = load_calibration(args)
    proof = json.loads((args.profile_dir / 'profile.json').read_text())
    if proof['model_identity'] != identity(args.model_dir):
        raise ValueError('Profile model identity mismatch')
    model_path = args.profile_dir / 'selected_block.onnx'
    input_path = args.profile_dir / 'selected_block_inputs.npz'
    if sha(model_path) != proof['selected_block_model_sha256'] or sha(input_path) != proof['selected_block_inputs_sha256']:
        raise ValueError('Block capture artifacts have changed')
    model = onnx.load(str(model_path))
    with np.load(input_path) as capture:
        inputs = {n: capture[n] for n in capture.files}
    values = evaluator(model, data['scales']).run(None, inputs, intermediate=True)
    arrays = {v.name: numpy_helper.to_array(v) for v in model.graph.initializer}
    manifest, packed = [], {}
    for i, node in enumerate(n for n in model.graph.node if n.op_type == 'Conv'):
        attrs = {a.name: helper.get_attribute_value(a) for a in node.attribute}
        x = values[node.input[0]]
        sx, sy = data['scales'][node.input[0]], data['scales'][node.output[0]]
        bias = arrays.get(node.input[2]) if len(node.input) > 2 else None
        qw, sw, qb = conv_parameters(arrays[node.input[1]], bias, sx)
        qx = quantize(x, sx)
        stride = attrs.get('strides', [1])[0]; pads = tuple(attrs.get('pads', [0, 0]))
        dilation = attrs.get('dilations', [1])[0]; group = attrs.get('group', 1)
        acc = conv1d(qx, qw, qb, stride, pads, dilation, group)
        qy = requantize(acc, sx*sw/sy)
        np.testing.assert_array_equal(qy, quantize(values[node.output[0]], sy))
        prefix = 'conv_' + str(i)
        multipliers, shifts = requant_parameters(sx*sw/sy)
        packed.update({prefix+'_input': qx, prefix+'_weights': qw, prefix+'_weight_scales': sw,
                       prefix+'_accumulator': acc, prefix+'_output': qy,
                       prefix+'_multipliers': multipliers, prefix+'_shifts': shifts,
                       prefix+'_bias': qb if qb is not None else np.zeros(qw.shape[0], np.int32)})
        manifest.append({'prefix': prefix, 'node': node.name, 'input_scale': sx, 'output_scale': sy,
                         'stride': stride, 'pads': list(pads), 'dilation': dilation, 'group': group,
                         'input_shape': list(qx.shape), 'weight_shape': list(qw.shape), 'output_shape': list(qy.shape)})
    reductions = []
    for i, node in enumerate(n for n in model.graph.node if n.op_type == 'ReduceSum'):
        source = node.input[0]
        if source not in data['scales'] or values[source].dtype != np.float32:
            continue
        qx = quantize(values[source], data['scales'][source])
        # Export actual graph axis and valid-length-masked input for FPGA reduction.
        axes = tuple(int(v) for v in values[node.input[1]]) if len(node.input) > 1 else None
        total = np.sum(qx.astype(np.int64), axis=axes, keepdims=True)
        if np.any(np.abs(total) > (1 << 31)-1):
            raise OverflowError('Reduction vector overflow')
        prefix = 'se_' + str(i)
        packed[prefix+'_input'] = qx; packed[prefix+'_sum'] = total.astype(np.int32)
        reductions.append({'prefix': prefix, 'node': node.name, 'axes': list(axes),
                           'activation_scale': data['scales'][source]})
    primitives = []
    for node in model.graph.node:
        if node.op_type not in ('Add', 'Mul', 'Relu', 'Where') or node.output[0] not in data['scales']:
            continue
        prefix = 'primitive_' + str(len(primitives))
        packed[prefix+'_expected'] = quantize(values[node.output[0]], data['scales'][node.output[0]])
        entry = {'prefix': prefix, 'node': node.name, 'kind': node.op_type,
                 'output_scale': data['scales'][node.output[0]], 'inputs': []}
        for j, name in enumerate(node.input):
            value = values[name]
            scale = data['scales'].get(name)
            key = prefix+'_input_'+str(j)
            if scale is not None:
                packed[key] = quantize(value, scale)
            elif node.op_type == 'Mul' and j == 1:
                packed[key] = np.rint(value.astype(np.float64)*32768).astype(np.uint16)
            else:
                packed[key] = value
            entry['inputs'].append({'key': key, 'scale': scale, 'dtype': str(packed[key].dtype)})
        primitives.append(entry)
    for name, value in inputs.items():
        packed['feed::'+name] = value
    for output in model.graph.output:
        packed['expected::'+output.name] = values[output.name]
    args.out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out/'vectors.npz', **packed)
    write_json(args.out/'manifest.json', {'schema': 1, 'block_id': proof['selected_block_id'],
               'model_identity': identity(args.model_dir), 'calibration_sha256': sha(args.calibration),
               'sources_sha256': sources(), 'vectors_sha256': sha(args.out/'vectors.npz'),
               'convolutions': manifest, 'se_reductions': reductions, 'primitives': primitives,
               'hardware_execution': False,
               'quantization': 'symmetric [-127,127], INT32 bias/accumulator, Q31 nearest-even Conv output',
               'host_boundaries': 'SE MLP/sigmoid FP32; FPGA gate Q0.15, residual Q16 alignment, INT8 output',
               'limits': ['Representative whole-model WER and physical bit parity are required before expansion.',
                          'Vector capture is a host regression, not hardware verification.']})
    print('exported', len(manifest), 'convolutions and', len(reductions), 'SE reduction')


def evaluate(args):
    data = load_calibration(args)
    records = corpus(args.manifest, ('evaluation', 'test'))
    if set(data['audio_sha256']) & {r['audio_sha256'] for r in records} or set(data['ids']) & {r['id'] for r in records}:
        raise ValueError('Calibration/evaluation overlap')
    model = load_model(args)
    baseline = session(model, args.threads)
    if args.engine == 'integer':
        candidate = evaluator(model, data['scales'], args.exclude_blocks)
    else:
        candidate = session(qdq_model(model, data['scales'], args.exclude_blocks), args.threads)
    frontend = Frontend(args.model_dir)
    vocab = (args.model_dir / 'vocab.txt').read_text().splitlines()
    rows = []
    for record in records:
        inputs = feed(frontend, record['path'])
        reference = baseline.run(None, inputs)
        start = time.perf_counter(); actual = candidate.run(None, inputs); seconds = time.perf_counter()-start
        np.testing.assert_array_equal(actual[1], reference[1])
        if actual[0].shape != reference[0].shape or not np.all(np.isfinite(actual[0])):
            raise ValueError('Invalid candidate output')
        ref_text = record.get('text', record.get('reference'))
        a = decode(reference[0][0], reference[1][0], vocab)
        b = decode(actual[0][0], actual[1][0], vocab)
        ea, words = errors(ref_text, a); eb, _ = errors(ref_text, b)
        if words == 0:
            raise ValueError('Empty reference transcript')
        rows.append({'id': record['id'], 'audio_sha256': record['audio_sha256'], 'reference': ref_text,
                     'reference_words': words, 'cpu_text': a, 'candidate_text': b,
                     'cpu_errors': ea, 'candidate_errors': eb,
                     'max_log_probability_difference': float(np.max(np.abs(actual[0]-reference[0]))),
                     'candidate_diagnostic_seconds': seconds, 'encoded_length': int(actual[1][0])})
        print(record['id'], 'errors', ea, eb, 'seconds', round(seconds, 3), flush=True)
    count = sum(r['reference_words'] for r in rows)
    cpu = sum(r['cpu_errors'] for r in rows)/count
    other = sum(r['candidate_errors'] for r in rows)/count
    categories = {c for r in records for c in r.get('categories', [r.get('category', 'unspecified')])}
    required = {'quiet', 'accent', 'numbers', 'names', 'noise'}
    report = {'engine': args.engine, 'hardware_execution': False, 'model_identity': identity(args.model_dir),
              'sources_sha256': sources(), 'calibration_sha256': sha(args.calibration),
              'evaluation_manifest_sha256': sha(args.manifest), 'exclude_blocks': args.exclude_blocks,
              'environment': environment(), 'cpu_wer': cpu, 'candidate_wer': other,
              'absolute_wer_degradation': other-cpu, 'regression_within_one_pp': other-cpu <= .01,
              'required_category_coverage': required <= categories, 'final_accuracy_gate_claimed': False,
              'rtl_expansion_approved': False, 'clips': rows,
              'limits': ['Small regression is not representative accuracy acceptance.',
                         'Integer Python reference timing is not a latency prediction.',
                         'QDQ uses FP32 bias/SE/residual arithmetic; integer engine uses INT32 bias, Q31 Conv, Q16 residual, Q0.15 gate.']}
    write_json(args.out, report)
    print(json.dumps({k: report[k] for k in ('cpu_wer', 'candidate_wer', 'absolute_wer_degradation',
                                          'regression_within_one_pp')}, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-dir', type=Path, default=ROOT/'research/export/citrinet-256-ls')
    p.add_argument('--threads', type=int, default=4)
    sub = p.add_subparsers(dest='command', required=True)
    prof = sub.add_parser('profile'); prof.add_argument('wav', type=Path)
    prof.add_argument('--warmups', type=int, default=3); prof.add_argument('--runs', type=int, default=20)
    prof.add_argument('--out', type=Path, required=True)
    cal = sub.add_parser('calibrate'); cal.add_argument('--manifest', type=Path, required=True)
    cal.add_argument('--out', type=Path, required=True)
    for cmd in ('build', 'evaluate', 'vectors'):
        parser = sub.add_parser(cmd)
        parser.add_argument('--calibration', type=Path, required=True)
        parser.add_argument('--exclude-blocks', type=int, nargs='*', default=[])
        parser.add_argument('--out', type=Path, required=True)
        if cmd == 'evaluate':
            parser.add_argument('--manifest', type=Path, required=True)
            parser.add_argument('--engine', choices=('integer', 'qdq'), default='integer')
        if cmd == 'vectors':
            parser.add_argument('--profile-dir', type=Path, required=True)
    args = p.parse_args()
    if args.threads < 1 or (args.command == 'profile' and (args.runs < 1 or args.warmups < 0)):
        p.error('Invalid threads/runs/warmups')
    globals()[args.command](args)


if __name__ == '__main__':
    main()
