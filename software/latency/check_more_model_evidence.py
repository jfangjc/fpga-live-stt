"""Require independent proofs before broader FPGA retention is measured."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/latency'))
from check_scale_split_evidence import verify as verify_scale
def verify():
    verify_scale()
    sha=lambda name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    for report,test in (
        ('branch512_stride_tail_oracle.json','validate_branch512_stride_tail_oracle.py'),
        ('branch512_stride_tail_pairs.json','test_stride_pointwise.py'),
        ('branch512_stride_tail_mock_transport.json','test_branch512_stride_tail_transport.py'),
        ('branch512_more_pool_oracle.json','validate_branch512_more_pool_oracle.py')):
        p=json.loads((ROOT/'reports/fused'/report).read_text())
        assert p['complete'] and not p['hardware_execution']
        assert p['stride_tail_source_sha256']==sha('software/latency/retain_stride_pointwise.py')
        assert p['library_sha256']==sha('software/ort_fpga_stream_branch512/libort_fpga.so')
        assert p['source_sha256']==sha('software/latency/'+test)
        if 'oracle' in report:
            assert p['all_cpu_logits_bit_exact'] and len(p['clips'])==36 and p['transactions']==24 and p['total_pairs']==128
            assert p['cpu_model_sha256']==sha('research/fused/cpu-int8-cse.onnx')
            assert p['compiler_sha256']==sha('software/ort_fpga_stream_branch512/branch_graph.py')
            assert p['scale_split_source_sha256']==sha('software/latency/split_scale_pairs.py')
            if 'pool' in report:
                assert p['se_pool_regions']==21
                assert p['se_pool_library_sha256']==sha('software/latency/libse_pool.so')
                assert p['se_pool_transform_sha256']==sha('software/latency/se_pool.py')
        elif 'pairs' in report:
            assert p['all_outputs_bit_exact'] and len(p['cases'])==104
        else:
            assert p['prefixes']==24 and p['packet_checks']==288 and p['error_checks']==159
            assert p['all_model_prefixes_independently_exact']
            assert p['transport_source_sha256']==sha('software/ort_fpga_stream_branch512/qnc_transport.c')
    print('PASS: broader retained graph, three independent PW tails, packet guards and exact pooling')
if __name__=='__main__':verify()
