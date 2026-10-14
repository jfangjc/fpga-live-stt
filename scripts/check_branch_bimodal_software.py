"""Require exact model arithmetic, masks, packets and primitive evidence."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
exec((ROOT/'scripts/check_compact_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_compact_software.py')})
oracle=json.loads((ROOT/'reports/fused/branch_transport_oracle.json').read_text())
assert oracle['complete'] and oracle['all_cpu_logits_bit_exact'] and len(oracle['clips'])==36 and oracle['residual_projections']==21
for key,name in (('library_sha256','software/ort_fpga_stream_branch/libort_fpga.so'),
    ('runtime_source_sha256','software/ort_fpga_stream_branch/pointwise.cc'),('compiler_sha256','software/ort_fpga_stream_branch/branch_graph.py'),
    ('source_sha256','software/latency/validate_branch_oracle.py')):assert oracle[key]==sha(ROOT/name),name
masks=json.loads((ROOT/'reports/fused/branch_mask_validation.json').read_text())
assert masks['complete'] and masks['all_outputs_bit_exact'] and len(masks['cases'])==294
assert masks['library_sha256']==oracle['library_sha256'] and masks['source_sha256']==sha(ROOT/'software/latency/test_branch_masks.py')
mock=json.loads((ROOT/'reports/fused/branch_mock_transport.json').read_text())
assert mock['complete'] and mock['all_model_prefixes_independently_exact'] and mock['prefixes']==23 and mock['branches']==21
assert mock['packet_checks']==276 and mock['error_checks']==155 and not mock['hardware_execution']
for key,name in (('library_sha256','software/ort_fpga_stream_branch_transport/libort_fpga.so'),
    ('runtime_source_sha256','software/ort_fpga_stream_branch_transport/pointwise.cc'),
    ('transport_source_sha256','software/ort_fpga_stream_branch_transport/qnc_transport.c'),
    ('source_sha256','software/latency/test_branch_transport.py')):assert mock[key]==sha(ROOT/name),name
unit=json.loads((ROOT/'reports/fused/branch_bimodal_unit_evidence.json').read_text())
assert unit['complete'] and unit['mac_model_vendor_conformance_cycles']==6000 and unit['depthwise_unit_cases']==180
for name,value in unit['sources_sha256'].items():assert sha(ROOT/name)==value,name
print('PASS: exact residual model/masks, independent two-output transport, compact quantizer and bimodal DW/MAC units')
for name,count,test in (('branch_backend_oracle.json',36,'validate_branch_backend_oracle.py'),
                        ('branch_backend_masks.json',294,'test_branch_backend_masks.py')):
    report=json.loads((ROOT/'reports/fused'/name).read_text())
    assert report['complete'] and not report['hardware_execution']
    assert len(report['clips'] if count==36 else report['cases'])==count
    assert report['library_sha256']==mock['library_sha256']
    assert report['compiler_sha256']==sha(ROOT/'software/ort_fpga_stream_branch_transport/branch_graph.py')
    assert report['source_sha256']==sha(ROOT/'software/latency'/test)
    if count==36:
        assert report['runtime_source_sha256']==mock['runtime_source_sha256'] and report['all_cpu_logits_bit_exact']
    else:assert report['all_outputs_bit_exact']
print('PASS: rebuilt physical-backend oracle and 294 independent masked blocks')
