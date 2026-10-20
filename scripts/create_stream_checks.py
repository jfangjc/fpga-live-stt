"""Artifact-bound physical/full-path checks for 100 streamed pairs."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'software/latency/chain_benchmark.py').read_text()
text=text.replace("sys.path.insert(0,str(ROOT/'software/ort_fpga_chain'))", "sys.path.insert(0,str(ROOT/'software/ort_fpga_stream_exact'))")
text=text.replace('from graph import candidate','from pair_graph import candidate').replace('from chain_graph import compile_chains','from stream_graph import compile_chains')
text=text.replace('from boundary_lut import transform','from boundary_lut import transform\nfrom residual_tail import transform as tails')
text=text.replace('chain_firmware_evidence','stream_firmware_evidence').replace('asr-v3-chain','asr-v3-stream')
text=text.replace('software/ort_fpga_chain','software/ort_fpga_stream_exact').replace('deployment/experimental-chain','deployment/experimental-stream')
text=text.replace('short_chain_protocol','stream_chain_protocol')
text=text.replace('transform(candidate(onnx.load(path)))[0]', 'transform(candidate(onnx.load(path),False)[0])[0]')
text=text.replace('transform(candidate(onnx.load(path),True))[0]', 'transform(candidate(onnx.load(path),True)[0])[0]')
text=text.replace("assert len(groups)==10 and sum(len(g['pairs']) for g in groups)==32", "assert len(groups)==23 and sum(len(g['pairs']) for g in groups)==100\n    cpu,tail_records=tails(cpu);physical,_=tails(physical);oracle,_=tails(oracle)")
text=text.replace('for p in libraries:opt.register_custom_ops_library(str(p))', "libraries=list(libraries)\n    if any(n.domain=='prototype.cpu.residual' for n in graph.graph.node):libraries.append(ROOT/'software/latency/libresidual_tail.so')\n    for p in libraries:opt.register_custom_ops_library(str(p))")
text=text.replace("(32 if kind=='fpga' else 0)", "(100 if kind=='fpga' else 0)").replace("(32 if kind=='oracle' else 0)","(100 if kind=='oracle' else 0)")
text=text.replace('chain_graph.py','stream_graph.py')
text=text.replace("'warm_transactions':10,'retained_pairs':32", "'warm_transactions':23,'retained_pairs':100,'weight_updates_per_inference':200,'weight_transfers_inside_timing':True")
text=text.replace("'retained_boundaries':22", "'retained_boundaries':77")
text=text.replace("'boundary_transform_sha256':sha(ROOT/'software/latency/boundary_lut.py'),", "'boundary_transform_sha256':sha(ROOT/'software/latency/boundary_lut.py'),\n            'residual_tail_library_sha256':sha(ROOT/'software/latency/libresidual_tail.so'),\n            'pair_compiler_sha256':sha(ROOT/'software/ort_fpga_stream_exact/pair_graph.py'),")
text=text.replace('for p in (library,boundary,driver):', "for p in (library,boundary,driver,ROOT/'software/latency/libresidual_tail.so'):")
(ROOT/'software/latency/stream_benchmark.py').write_bytes(text.encode())
for name in ('validate_chain_physical.py','tune_tail_policy.py','confirm_tail_latency.py'):
    text=(ROOT/'software/latency'/name).read_text().replace('from chain_benchmark import','from stream_benchmark import').replace('from tail_benchmark import','from stream_benchmark import')
    text=text.replace("items['tail_library']", "(ROOT/'software/latency/libresidual_tail.so')")
    text=text.replace('cpu_graph(items,c)', "items['cpu']").replace('cpu_graph(items,cpu_policy)', "items['cpu']")
    text=text.replace("assert results['fpga']['counters']['loads']==0 and results['fpga']['counters']['ioctls']==10", "assert results['fpga']['counters']['loads']==200 and results['fpga']['counters']['ioctls']==23")
    text=text.replace("assert physical['counters']['ioctls']==10+(64 if not rows else 0)", "assert physical['counters']['ioctls']==23 and physical['counters']['loads']==200")
    text=text.replace('np.testing.assert_array_equal(actual,expected)', 'np.testing.assert_array_equal(actual,expected);np.testing.assert_array_equal(actual,cpu_logits)')
    if name=='confirm_tail_latency.py':
        text=text.replace("'cold_fpga':cold", "'first_fpga_inference':cold")
        text=text.replace("Cold weight loading", "Weight loading included in every inference")
        text=text.replace("contexts.append(summary);", "summary['meets_30_percent']=bool(summary['latency_reduction_percent']>=30 and summary['fpga_p95']<summary['cpu_p95'])\n        contexts.append(summary);")
        text=text.replace("'timing_acceptance':all(c['meets_20_percent'] for c in contexts),", "'timing_acceptance':all(c['meets_20_percent'] for c in contexts),'thirty_percent_acceptance':all(c['meets_30_percent'] for c in contexts),")
    if name=='tune_tail_policy.py':
        text=text.replace("cpu_policies={str(c['context_seconds']):c['selected']['policy'] for c in cpu_screen['contexts']}",
                          "cpu_policies={str(c['context_seconds']):c['selected']['policy'] for c in cpu_screen['contexts']}\nassert all(c['graph']=='tail' for c in cpu_policies.values())")
    out={'validate_chain_physical.py':'validate_stream_physical.py','tune_tail_policy.py':'tune_stream_policy.py','confirm_tail_latency.py':'confirm_stream_latency.py'}[name]
    (ROOT/'software/latency'/out).write_bytes(text.encode())
print('Created streamed block physical parity and timing checks; all weight uploads are timed')
