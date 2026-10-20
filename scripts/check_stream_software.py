"""Refuse hardware work until the larger exact arithmetic passes CPU parity."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
proof=json.loads((ROOT/'reports/fused/stream_transport_oracle.json').read_text())
assert proof['complete'] and proof['all_cpu_logits_bit_exact'] and proof['all_diagnostic_transcripts_equal']
assert proof['retained_pairs']==100 and proof['transactions']==23 and len(proof['clips'])==36
for key,name in (('library_sha256','software/ort_fpga_stream_exact/libort_fpga.so'),
                 ('runtime_source_sha256','software/ort_fpga_stream_exact/pointwise.cc'),
                 ('pair_compiler_sha256','software/ort_fpga_stream_exact/pair_graph.py'),
                 ('chain_compiler_sha256','software/ort_fpga_stream_exact/stream_graph.py'),
                 ('cpu_model_sha256','research/fused/cpu-int8-cse.onnx')):
    assert proof[key]==sha(ROOT/name),name
integer=json.loads((ROOT/'reports/fused/exact_requant_integer_validation.json').read_text())
assert integer['complete'] and integer['all_float32_bit_exact'] and integer['random_cases']==1000000
assert integer['targeted_half_cases']==100000 and integer['rtl_vectors']==2400
assert integer['fixture_sha256']==sha(ROOT/'verification/exact-requant/quant.mem')
assert integer['reference_sha256']==sha(ROOT/'software/latency/exact_requant_reference.py')
log=(ROOT/'build/exact_requant_sim/exact_requant_sim.sim/sim_1/behav/xsim/simulate.log').read_text()
assert 'PASS: 9600 float32-equivalent lanes' in log and not re.search(r'Fatal:|ERROR:',log)
print('PASS: 100-pair CPU-exact full-model arithmetic and 1.1M integer/float32 tests')
