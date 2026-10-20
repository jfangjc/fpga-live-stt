"""Preserve quantizer equivalence evidence; do not adopt a non-winning path."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
library=ROOT/'software/latency/libresidual_tail_recip64.so'
source=ROOT/'software/latency/residual_tail_recip64.cc'
paths=[library,source,Path(__file__)]
boundary=ROOT/'reports/fused/residual_tail_recip64_boundaries.json'
validation=ROOT/'reports/fused/residual_tail_recip64_validation.json'
benchmark=ROOT/'reports/fused/residual_tail_recip64_operator_benchmark.json'
p=json.loads(boundary.read_text());v=json.loads(validation.read_text());b=json.loads(benchmark.read_text())
assert p['complete'] and p['all_finite_float32_quantized_bytes_equal'] and len(p['regions'])==21
assert all(len(r['first_ordered_float_keys'])==255 and r['all_byte_transitions_equal'] for r in p['regions'])
assert p['rounding_mode']=='FE_TONEAREST' and not p['intermediate_quotients_claimed_equal']
assert p['implementation_sha256']==sha(source) and p['library_sha256']==sha(library)
proof_source=ROOT/'software/latency/prove_recip64_byte_boundaries.py'
assert p['source_sha256']==sha(proof_source)
assert v['complete'] and v['all_bit_exact'] and len(v['micro_cases'])==567 and len(v['full_model_cases'])==36
assert v['implementation_sha256']==sha(source) and v['library_sha256']==sha(library)
test=ROOT/'software/latency/test_residual_tail_recip64.py';timer=ROOT/'software/latency/benchmark_residual_tail_recip64.py'
assert v['source_sha256']==sha(test) and b['source_sha256']==sha(timer)
assert b['complete'] and b['all_outputs_bit_exact'] and b['runs_per_case']==100 and len(b['cases'])==105
assert b['vector_library_sha256']==sha(library) and b['validation_sha256']==sha(validation)
assert b['original_library_sha256']==sha(ROOT/'software/latency/libresidual_tail_maskfast.so')
paths += [boundary,validation,benchmark,proof_source,test,timer,ROOT/'scripts/create_residual_tail_recip64.py']
paths += [ROOT/'software/latency/residual_tail_maskfast.cc',ROOT/'software/latency/libresidual_tail_maskfast.so',ROOT/'research/fused/cpu-int8-cse.onnx']
report={'complete':True,'hardware_execution':False,'adopted':False,
        'reason':'No useful speed improvement over current maskfast tail at target model lengths',
        'byte_transitions_checked':5355,'finite_float32_byte_equivalence_proved_for_checkpoint_scales':True,
        'intermediate_quotient_equivalence_claimed':False,'full_path_gain_proven':False,
        'operator_cases':105,'faster_cases':sum(r['reduction_percent']>0 for r in b['cases']),
        'sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}}
(ROOT/'reports/fused/residual_tail_recip64_experiment_evidence.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS: 5,355 byte transitions, 567 operators and 36 model comparisons bound; not adopted')
