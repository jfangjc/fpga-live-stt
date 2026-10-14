"""Require source-bound model, mask, transport and RTL evidence before synthesis."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
exec((ROOT/'scripts/check_branch_bimodal_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_branch_bimodal_software.py')})
library=ROOT/'software/ort_fpga_stream_branch512/libort_fpga.so'
for name,count,test in (('branch512_oracle.json',36,'validate_branch512_oracle.py'),('branch512_masks.json',294,'test_branch512_masks.py')):
    proof=json.loads((ROOT/'reports/fused'/name).read_text());assert proof['complete'] and not proof['hardware_execution']
    assert len(proof['clips'] if count==36 else proof['cases'])==count
    assert proof['library_sha256']==sha(library) and proof['source_sha256']==sha(ROOT/'software/latency'/test)
    assert proof['compiler_sha256']==sha(ROOT/'software/ort_fpga_stream_branch512/branch_graph.py')
    if count==36:assert proof['all_cpu_logits_bit_exact'] and proof['runtime_source_sha256']==sha(ROOT/'software/ort_fpga_stream_branch512/pointwise.cc')
    else:assert proof['all_outputs_bit_exact']
mock=json.loads((ROOT/'reports/fused/branch512_mock_transport.json').read_text())
assert mock['complete'] and mock['packet_checks']==276 and mock['error_checks']==155 and mock['all_model_prefixes_independently_exact']
for key,name in (('library_sha256','software/ort_fpga_stream_branch512/libort_fpga.so'),
                 ('runtime_source_sha256','software/ort_fpga_stream_branch512/pointwise.cc'),
                 ('transport_source_sha256','software/ort_fpga_stream_branch512/qnc_transport.c'),
                 ('source_sha256','software/latency/test_branch512_transport.py')):assert mock[key]==sha(ROOT/name),name
rtl=json.loads((ROOT/'reports/fused/branch512_regression_evidence.json').read_text())
assert rtl['complete'] and rtl['pipelined_cases']==25 and rtl['full_pipeline_reset_replay_cases']==2
for name,value in rtl['sources_sha256'].items():assert sha(ROOT/name)==value,name
print('PASS: isolated 512-MAC residual native arithmetic, masks, transport and elastic pipeline RTL')
