"""CPU-only diagnosis of partition fallback; never FPGA performance evidence.

Run each thread/pool setting in a separate process. Shared ORT pool configuration
must precede creation of every session, including the complete CPU comparator.
Pointwise operations use FP32 NumPy BLAS here so the CPU fallback can be isolated.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import onnxruntime as ort
import partition
from citrinet_adapter import ROOT, Frontend, read_audio, decode


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wav',type=Path)
    parser.add_argument('--pool',choices=['per-session','shared'],default='shared')
    parser.add_argument('--threads',type=int,choices=[1,2,4],default=4)
    parser.add_argument('--warmups',type=int,default=3)
    parser.add_argument('--runs',type=int,default=20)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.runs<1 or args.warmups<0: parser.error('Invalid run/warmup count')
    original_options=partition.options
    if args.pool=='shared':
        if not hasattr(ort,'set_global_thread_pool_sizes'):
            raise RuntimeError('Installed ORT does not expose shared thread pool support')
        ort.set_global_thread_pool_sizes(args.threads,1)
        def shared_options(threads):
            options=original_options(threads)
            options.use_per_session_threads=False
            options.intra_op_num_threads=0
            options.inter_op_num_threads=0
            # Request non-spinning session behavior. Global-pool implementation
            # may override this; the report records the request, not an assertion
            # that workers never spin. The shared-pool result must be measured.
            options.add_session_config_entry('session.intra_op.allow_spinning','0')
            options.add_session_config_entry('session.inter_op.allow_spinning','0')
            return options
        partition.options=shared_options
    model=ROOT/'research/export/citrinet-256-ls'
    audio=read_audio(args.wav)
    features,lengths=Frontend(model)(audio)
    feeds={'features':features,'feature_lengths':lengths}
    started=time.perf_counter()
    full=ort.InferenceSession(str(model/'model.onnx'),partition.options(args.threads),
                              providers=['CPUExecutionProvider'])
    graph=partition.PartitionGraph(model/'model.onnx',threads=args.threads,
                                  emulate=True,region_threads=args.threads,fp32_partition=True)
    initialization=time.perf_counter()-started
    reference=full.run(None,feeds)
    outputs=graph.run(feeds)
    np.testing.assert_array_equal(outputs[1],reference[1])
    np.testing.assert_allclose(outputs[0],reference[0],rtol=1e-4,atol=1e-3)
    expected_text=decode(reference[0][0],reference[1][0],(model/'vocab.txt').read_text().splitlines())
    actual_text=decode(outputs[0][0],outputs[1][0],(model/'vocab.txt').read_text().splitlines())
    if expected_text!=actual_text: raise AssertionError('FP32 partition transcript differs from full graph')
    for _ in range(args.warmups): full.run(None,feeds); graph.run(feeds)
    rows=[]
    for index in range(args.runs):
        # Alternate order to reduce a consistent cache/thermal ordering bias.
        def run_full():
            begin=time.perf_counter(); full.run(None,feeds); return time.perf_counter()-begin
        def run_partition():
            begin=time.perf_counter(); graph.run(feeds); return time.perf_counter()-begin
        if index%2:
            partition_seconds=run_partition(); full_seconds=run_full()
        else:
            full_seconds=run_full(); partition_seconds=run_partition()
        rows.append({'full_cpu_graph_seconds':full_seconds,'partition_seconds':partition_seconds,
                     'cpu_region_seconds':sum(p['seconds'] for p in graph.last_profile if p['kind']=='cpu'),
                     'fp32_pointwise_seconds':sum(p['seconds'] for p in graph.last_profile if p['kind']=='fpga'),
                     'partition_profile':graph.last_profile})
    report={'purpose':'CPU fallback diagnosis only; no FPGA or end-to-end acceptance claim',
            'hardware_execution':False,'precision':'FP32 complete graph and FP32 partition',
            'pool':args.pool,'threads':args.threads,'session_allow_spinning_requested':False if args.pool=='shared' else None,
            'onnxruntime_version':ort.__version__,'initialization_seconds':initialization,
            'warmups':args.warmups,'runs':rows,'audio_seconds':len(audio)/16000,
            'wav_sha256':hashlib.sha256(args.wav.read_bytes()).hexdigest(),
            'model_sha256':hashlib.sha256((model/'model.onnx').read_bytes()).hexdigest(),
            'sources_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in [Path(__file__),ROOT/'software/runtime/partition.py',ROOT/'software/model-tools/citrinet_cpu.py']},
            'thread_environment':{k:os.environ.get(k) for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']},
            'fp32_output_parity_passed':True,'transcript':actual_text}
    for metric in ['full_cpu_graph_seconds','partition_seconds','cpu_region_seconds','fp32_pointwise_seconds']:
        report[metric+'_p50']=float(np.percentile([r[metric] for r in rows],50))
        report[metric+'_p95']=float(np.percentile([r[metric] for r in rows],95))
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='runs'},indent=2))


if __name__=='__main__': main()
