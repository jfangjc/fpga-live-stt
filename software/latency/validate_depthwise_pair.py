"""Capture and validate a retained UINT8 depthwise/mask/pointwise contract.

Software oracle only. No speed or physical FPGA execution claim.
"""
import argparse
import collections
import copy
import json
from pathlib import Path
import sys
import numpy as np
import onnx
from onnx import helper, numpy_helper
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'software/ort_fpga_bulk'))
from probe import session
from common import Frontend, read_audio, decode, corpus, errors, sha, identity, expose, write_json
from oracle import requant_parameters, round_shift_even


def parameters(node, arrays):
    w = arrays[node.input[3]]
    zx = int(arrays[node.input[2]]); zy = int(arrays[node.input[7]])
    sw = arrays[node.input[4]]
    assert np.all(arrays[node.input[5]] == 0) and w.dtype == np.int8
    # Preserve the float32 ratio convention of the accepted physical pointwise.
    ratios = (arrays[node.input[1]] * sw) / arrays[node.input[6]]
    multipliers, shifts = requant_parameters(ratios)
    bias = arrays[node.input[8]] if len(node.input) == 9 else np.zeros(w.shape[0], np.int32)
    return w, zx, zy, bias, multipliers, shifts


def integer_conv(x, node, arrays):
    w, zx, zy, bias, multipliers, shifts = parameters(node, arrays)
    attrs = {a.name: helper.get_attribute_value(a) for a in node.attribute}
    assert attrs.get('strides', [1]) == [1] and attrs.get('dilations', [1]) == [1]
    c = x.astype(np.int64) - zx
    if attrs.get('group', 1) == w.shape[0] and w.shape[1] == 1:
        pads = attrs.get('pads', [0, 0])
        assert pads == [w.shape[2]//2]*2 and w.shape[2] % 2
        padded = np.pad(c, ((0, 0), (0, 0), tuple(pads)))
        acc = np.zeros_like(c)
        for tap in range(w.shape[2]):
            acc += padded[:, :, tap:tap+x.shape[2]] * w[:, 0, tap][None, :, None]
    else:
        assert w.shape[2] == 1 and attrs.get('group', 1) == 1
        acc = w[:, :, 0].astype(np.int64) @ c
    acc += bias[None, :, None]
    assert np.all(acc >= -(1 << 31)) and np.all(acc < (1 << 31))
    y = np.empty(acc.shape, np.uint8)
    for channel, (multiplier, shift) in enumerate(zip(multipliers, shifts)):
        y[:, channel] = np.clip(round_shift_even(acc[:, channel]*int(multiplier), int(shift))+zy, 0, 255)
    return y


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    model_path = ROOT / 'research/fused/cpu-int8-cse.onnx'
    model = onnx.shape_inference.infer_shapes(onnx.load(str(model_path)))
    proof = json.loads(model_path.with_suffix('.json').read_text())
    directory = ROOT / 'research/export/citrinet-256-ls'
    assert sha(model_path) == proof['model_sha256'] and identity(directory) == proof['source_identity']
    arrays = {v.name:numpy_helper.to_array(v) for v in model.graph.initializer}
    by_name = {n.name:n for n in model.graph.node}
    dw = by_name['/encoder/encoder.1/mconv.5/conv/Conv_quant']
    pw = by_name['/encoder/encoder.1/mconv.6/conv/Conv_quant']
    mask = by_name['/encoder/encoder.1/mconv.6/Where'].input[0]
    assert pw.input[1:3] == dw.input[6:8], 'Intermediate scales must match'
    capture_names = [dw.input[0], dw.output[0], pw.input[0], pw.output[0], mask]
    capture = session(expose(model, capture_names))
    # Turn only the pair output into an override input. Upstream live branches
    # (including residual/length paths) still execute normally in this session.
    continuation = copy.deepcopy(model)
    removed = [n for n in continuation.graph.node if pw.output[0] in n.output]
    assert len(removed) == 1
    continuation.graph.node.remove(removed[0])
    infos = {v.name:v for v in list(model.graph.value_info)+list(model.graph.output)}
    continuation.graph.input.append(copy.deepcopy(infos[pw.output[0]]))
    onnx.checker.check_model(continuation)
    tail = session(continuation)
    baseline = session(model)
    frontend = Frontend(directory); vocab = (directory/'vocab.txt').read_text().splitlines()
    records = []
    for folder in ('user-recording', 'librispeech-mini', 'user-stress-ac'):
        records += corpus(ROOT/'research/eval'/folder/'evaluation.jsonl', ('evaluation','test'))
    rows = []; totals = {'cpu':0,'pair_oracle':0}; words = 0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    vectors = a.out.parent / 'depthwise_pair_vectors'
    vectors.mkdir(exist_ok=True)
    for record in records:
        full = read_audio(record['path'])
        for seconds in [None, .25, .5, 1]:
            if seconds and seconds > len(full)/16000: continue
            audio = full if seconds is None else full[:round(seconds*16000)]
            x, n = frontend(audio); x = np.ascontiguousarray(x[:, :, :int(n[0])])
            feed = {'features':x, 'feature_lengths':n}
            actual = dict(zip([v.name for v in capture.get_outputs()], capture.run(None, feed)))
            dy = integer_conv(actual[dw.input[0]], dw, arrays)
            intermediate = np.where(actual[mask], int(arrays[dw.input[7]]), dy).astype(np.uint8)
            # Reusing quantized bytes through mask must match original DQ/Where/Q
            # when supplied the original CPU depthwise result.
            mask_reference = np.where(actual[mask], int(arrays[dw.input[7]]), actual[dw.output[0]]).astype(np.uint8)
            np.testing.assert_array_equal(mask_reference, actual[pw.input[0]])
            py = integer_conv(intermediate, pw, arrays)
            cpu = baseline.run(None, feed)
            oracle = tail.run(None, dict(feed, **{pw.output[0]:py}))
            np.testing.assert_array_equal(cpu[1], oracle[1])
            texts = {'cpu':decode(cpu[0][0], cpu[1][0], vocab),
                     'pair_oracle':decode(oracle[0][0], oracle[1][0], vocab)}
            if seconds is None:
                for name in totals:
                    err, count = errors(record.get('reference',record.get('text')), texts[name])
                    totals[name] += err
                words += count
            rows.append({'id':record['id'], 'context_seconds':seconds, 'texts':texts,
                         'length_exact':True, 'mask_bytes_exact':True,
                         'input_shape':list(actual[dw.input[0]].shape),
                         'depthwise_byte_differences':int(np.count_nonzero(dy != actual[dw.output[0]])),
                         'pointwise_byte_differences':int(np.count_nonzero(py != actual[pw.output[0]])),
                         'max_valid_logit_difference':float(np.max(np.abs(cpu[0]-oracle[0])))})
            if record['id'] == records[0]['id'] and seconds == .5:
                w,zx,zy,bias,mult,shifts = parameters(dw,arrays)
                np.savez(vectors/'half_second.npz', input=actual[dw.input[0]], weights=w, bias=bias,
                         multipliers=mult, shifts=shifts, xzero=zx, yzero=zy, output=intermediate,
                         pointwise_output=py, mask=actual[mask])
                # Complete real channel vectors for HDL replay; one 16-byte word
                # per time tile, little-endian time lanes, padded input zero-point.
                def words_file(path, tensor, zero):
                    padded = np.pad(tensor[0], ((0,0),(0,(-tensor.shape[-1])%16)), constant_values=zero)
                    beats = padded.reshape(-1,16)
                    path.write_text('\n'.join(bytes(v[::-1]).hex() for v in beats)+'\n')
                words_file(vectors/'input.mem', actual[dw.input[0]], zx)
                words_file(vectors/'output.mem', intermediate, zy)
                (vectors/'weights.mem').write_text('\n'.join(bytes(v[0,::-1].view(np.uint8)).hex() for v in w)+'\n')
                (vectors/'params.mem').write_text('\n'.join(f'{int(zy):02x}{int(shifts[i]):02x}{int(mult[i]):08x}{int(bias[i]) & 0xffffffff:08x}' for i in range(len(w)))+'\n')
        print('PASS', record['id'], flush=True)
    report = {'complete':True, 'hardware_execution':False, 'latency_acceptance':False,
              'model_sha256':sha(model_path), 'source_sha256':sha(Path(__file__)),
              'depthwise':dw.name, 'pointwise':pw.name, 'retained_intermediate':'UINT8, original scale/zero point',
              'scope':'Software fixed-point pair oracle and diagnostic transcripts; no representative accuracy qualification',
              'errors':totals, 'words':words, 'wer_degradation_percentage_points':100*(totals['pair_oracle']-totals['cpu'])/words,
              'all_texts_exact':all(r['texts']['cpu']==r['texts']['pair_oracle'] for r in rows),
              'clips':rows, 'vector_files':{p.name:sha(p) for p in vectors.iterdir()}}
    write_json(a.out, report)
    assert report['wer_degradation_percentage_points'] <= 1


if __name__ == '__main__': main()
