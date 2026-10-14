"""Inventory retained-pair boundaries without claiming hardware speedups."""
import json
import sys
from pathlib import Path

import onnx
from onnx import helper, numpy_helper

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'software/fused'))
from common import sha, write_json
from graph import candidate


def main():
    path = ROOT / 'research/fused/cpu-int8-cse.onnx'
    model = onnx.load(path)
    producers = {o: n for n in model.graph.node for o in n.output}
    arrays = {v.name: numpy_helper.to_array(v) for v in model.graph.initializer}
    rows = []
    for pw in model.graph.node:
        if pw.op_type != 'QLinearConv':
            continue
        wp = arrays[pw.input[3]]
        if wp.ndim != 3 or wp.shape[2] != 1:
            continue
        try:
            q = producers[pw.input[0]]
            where = producers[q.input[0]]
            dq = producers[where.input[2]]
            dw = producers[dq.input[0]]
        except (KeyError, IndexError):
            continue
        if [q.op_type, where.op_type, dq.op_type, dw.op_type] != [
            'QuantizeLinear', 'Where', 'DequantizeLinear', 'QLinearConv'
        ]:
            continue
        wd = arrays[dw.input[3]]
        attrs = {a.name: helper.get_attribute_value(a) for a in dw.attribute}
        if wd.ndim != 3 or wd.shape[1] != 1 or attrs.get('group') != wd.shape[0]:
            continue
        row = {'depthwise': dw.name, 'pointwise': pw.name,
               'channels': int(wd.shape[0]), 'outputs': int(wp.shape[0]),
               'kernel': int(wd.shape[2]),
               'weight_bytes': int(wd.nbytes + wp.nbytes),
               'current_graph_contract_supported': False}
        try:
            candidate(model, dw.name, pw.name)
            row['current_graph_contract_supported'] = True
        except (AssertionError, KeyError, IndexError) as error:
            row['rejection'] = type(error).__name__
        rows.append(row)
    report = {'complete': True, 'cpu_model_sha256': sha(path),
              'source_sha256': sha(__file__),
              'graph_source_sha256': sha(Path(__file__).with_name('graph.py')),
              'boundaries': rows,
              'current_supported_count': sum(r['current_graph_contract_supported'] for r in rows),
              'physical_expansion_validated': False,
              'constraint': 'Current hardware caches one pair. Multiple graph replacements reload weights; inventory is not a speed claim.'}
    write_json(ROOT / 'reports/fused/pair_boundary_inventory.json', report)
    print(json.dumps({'boundaries': len(rows), 'supported': report['current_supported_count'],
                      'kernels': sorted({r['kernel'] for r in rows})}))


if __name__ == '__main__':
    main()
