"""Bind independent short-input timing to matching physical accuracy evidence."""
import argparse
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
from common import sha, write_json


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--benchmark',type=Path,required=True)
    ap.add_argument('--validation',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    bench=json.loads(a.benchmark.read_text()); physical=json.loads(a.validation.read_text())
    assert bench['complete'] and bench['hardware_execution'] and bench['runs']>=100
    assert physical['complete'] and physical['hardware_execution']
    assert physical['nodes']==bench['nodes']
    for key in ('cpu_model_sha256','library_sha256','firmware_sha256','pl_clock_hz'):
        assert physical[key]==bench[key]
    assert physical['feature_padding_policy']==bench['feature_padding_policy']=='trim_to_valid'
    assert physical['wer_degradation_percentage_points']<=1
    assert all(r['physical_oracle_bit_parity'] and r['within_tolerance'] and
               r['original_trimmed_cpu_text_exact'] and r['length_exact'] for r in physical['clips'])
    assert all(c['physical_oracle_bit_parity'] for c in bench['contexts'])
    if len(bench['nodes'])==1:
        assert all(r['results']['fpga']['fpga_counters']['loads']==0 and
                   r['results']['fpga']['fpga_counters']['ioctls']==1 for r in bench['paired_runs'])
    relative=a.validation.resolve().relative_to(ROOT/'reports/fused')
    bench.update(physical_validation_relative_path='reports/fused/'+relative.as_posix(),
                 physical_validation_sha256=sha(a.validation),
                 timing_source_report_sha256=sha(a.benchmark),
                 binding_source_sha256=sha(__file__))
    if 'dma_irq_effective_affinity' in bench:
        cores=set(bench['dma_irq_effective_affinity'].values())
        assert len(cores)==1 and cores<={'0','3'}
        bench['dma_irq_core']=int(next(iter(cores)))
    graph=a.benchmark.with_suffix('.onnx')
    assert sha(graph)==bench['fpga_graph_sha256']
    a.out.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(graph,a.out.with_suffix('.onnx'))
    write_json(a.out,bench)
    print('Bound',a.out,flush=True)


if __name__=='__main__':main()
