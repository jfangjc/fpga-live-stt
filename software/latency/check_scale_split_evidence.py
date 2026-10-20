"""Require source-bound independent pair, full-model and packet proofs."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def verify():
    sha=lambda p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
    compiler='software/latency/split_scale_pairs.py'
    library='software/ort_fpga_stream_branch512/libort_fpga.so'
    for name,test in (
        ('branch512_scale_split_oracle.json','validate_branch512_scale_split_oracle.py'),
        ('branch512_scale_split_pairs.json','test_scale_split_pairs.py'),
        ('branch512_scale_split_mock_transport.json','test_branch512_scale_split_transport.py')):
        p=json.loads((ROOT/'reports/fused'/name).read_text())
        assert p['complete'] and not p['hardware_execution']
        assert p['scale_split_source_sha256']==sha(compiler)
        assert p['library_sha256']==sha(library)
        assert p['source_sha256']==sha('software/latency/'+test)
        if 'oracle' in name:
            assert p['all_cpu_logits_bit_exact'] and len(p['clips'])==36 and p['transactions']==21 and p['total_pairs']==125
            assert p['cpu_model_sha256']==sha('research/fused/cpu-int8-cse.onnx')
            assert p['runtime_source_sha256']==sha('software/ort_fpga_stream_branch512/pointwise.cc')
            assert p['compiler_sha256']==sha('software/ort_fpga_stream_branch512/branch_graph.py')
        elif 'pairs' in name:
            assert p['all_outputs_bit_exact'] and len(p['cases'])==104
            assert p['cpu_model_sha256']==sha('research/fused/cpu-int8-cse.onnx')
        else:
            assert p['prefixes']==21 and p['packet_checks']==252 and p['error_checks']==147
            assert p['all_model_prefixes_independently_exact']
            assert p['runtime_source_sha256']==sha('software/ort_fpga_stream_branch512/pointwise.cc')
            assert p['transport_source_sha256']==sha('software/ort_fpga_stream_branch512/qnc_transport.c')
    print('PASS: 36 CPU-exact models, 104 independent two-pair cases and 252/147 packet/error checks')
if __name__=='__main__':verify()
