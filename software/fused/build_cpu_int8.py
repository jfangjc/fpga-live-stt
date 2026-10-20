"""Build a genuine ORT QLinearConv CPU comparator, separate from FPGA arithmetic."""
import argparse
import copy
from pathlib import Path
import time
import numpy as np
import onnx
from onnxruntime.quantization import (quantize_static, CalibrationDataReader, QuantFormat,
                                      QuantType, CalibrationMethod)
from common import (ROOT, corpus, Frontend, read_audio, decode, session, errors,
                    identity, sources, sha, write_json)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-dir', type=Path, default=ROOT/'research/export/citrinet-256-ls')
    p.add_argument('--calibration-manifest', type=Path, required=True)
    p.add_argument('--evaluation-manifest', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    calibration = corpus(args.calibration_manifest, ('calibration',))
    evaluation = corpus(args.evaluation_manifest, ('evaluation', 'test'))
    if {r['audio_sha256'] for r in calibration} & {r['audio_sha256'] for r in evaluation} or {r['id'] for r in calibration} & {r['id'] for r in evaluation}:
        raise ValueError('Calibration/evaluation overlap')
    frontend = Frontend(args.model_dir)

    class Reader(CalibrationDataReader):
        def __init__(self):
            self.records = iter(calibration)

        def get_next(self):
            record = next(self.records, None)
            if record is None:
                return None
            features, lengths = frontend(read_audio(record['path']))
            return {'features': features, 'feature_lengths': lengths}

    model = onnx.shape_inference.infer_shapes(onnx.load(str(args.model_dir/'model.onnx')))
    excluded = [n.name for n in model.graph.node if n.name.startswith('/decoder/')]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # ORT may externalize tensors in its input ModelProto while calibrating.
    # Keep the FP32 comparator's in-memory tensors independent of that mutation.
    quantize_static(copy.deepcopy(model), str(args.out), Reader(), quant_format=QuantFormat.QOperator,
                    op_types_to_quantize=['Conv'], per_channel=True,
                    activation_type=QuantType.QUInt8, weight_type=QuantType.QInt8,
                    nodes_to_exclude=excluded, calibrate_method=CalibrationMethod.MinMax,
                    calibration_providers=['CPUExecutionProvider'])
    candidate_model = onnx.load(str(args.out))
    integer_nodes = sum(n.op_type == 'QLinearConv' for n in candidate_model.graph.node)
    if integer_nodes == 0:
        raise ValueError('No actual QLinearConv operators were generated')
    baseline, candidate = session(model), session(candidate_model)
    vocab = (args.model_dir/'vocab.txt').read_text().splitlines()
    rows = []
    for record in evaluation:
        features, lengths = frontend(read_audio(record['path']))
        inputs = {'features': features, 'feature_lengths': lengths}
        reference = baseline.run(None, inputs)
        start = time.perf_counter(); actual = candidate.run(None, inputs); duration = time.perf_counter()-start
        np.testing.assert_array_equal(actual[1], reference[1])
        if actual[0].shape != reference[0].shape or not np.all(np.isfinite(actual[0])):
            raise ValueError('Invalid INT8 output')
        a, b = (decode(r[0][0], r[1][0], vocab) for r in (reference, actual))
        ea, count = errors(record.get('text', record.get('reference')), a)
        eb, _ = errors(record.get('text', record.get('reference')), b)
        if not count:
            raise ValueError('Empty reference')
        rows.append({'id': record['id'], 'audio_sha256': record['audio_sha256'], 'cpu_text': a,
                     'int8_text': b, 'cpu_errors': ea, 'int8_errors': eb, 'reference_words': count,
                     'diagnostic_seconds': duration})
        print(record['id'], 'CPU/INT8 errors', ea, eb, flush=True)
    count = sum(r['reference_words'] for r in rows)
    cpu = sum(r['cpu_errors'] for r in rows)/count
    integer = sum(r['int8_errors'] for r in rows)/count
    report = {'source_identity': identity(args.model_dir), 'model_sha256': sha(args.out),
              'sources_sha256': sources(), 'calibration_manifest_sha256': sha(args.calibration_manifest),
              'calibration_audio_sha256': [r['audio_sha256'] for r in calibration],
              'calibration_ids': [r['id'] for r in calibration],
              'evaluation_manifest_sha256': sha(args.evaluation_manifest),
              'precision': 'ORT QLinearConv: asymmetric UINT8 activations/per-channel INT8 weights/INT32 bias; FP32 SE/residual/decoder',
              'integer_conv_nodes': integer_nodes, 'hardware_execution': False,
              'cpu_wer': cpu, 'int8_wer': integer, 'absolute_wer_degradation': integer-cpu,
              'regression_within_one_pp': integer-cpu <= .01, 'final_accuracy_gate_claimed': False,
              'clips': rows}
    write_json(args.out.with_suffix('.json'), report)
    print('integer convs', integer_nodes, 'CPU WER', cpu, 'INT8 WER', integer)


if __name__ == '__main__':
    main()
