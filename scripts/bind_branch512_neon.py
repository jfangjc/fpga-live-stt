"""Bind transport-only changes and independent guarded byte-layout proofs."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
parent=ROOT/'software/ort_fpga_stream_branch512';new=ROOT/'software/ort_fpga_stream_branch512_neon'
for p in list(parent.glob('*'))+list((parent/'include').glob('*')):
    if p.is_file() and p.suffix in ('.cc','.h','.py','.sh'):assert p.read_bytes()==(new/p.relative_to(parent)).read_bytes(),p
mock=json.loads((ROOT/'reports/fused/branch512_neon_mock_transport.json').read_text())
assert mock['complete'] and mock['packet_checks']==288 and mock['error_checks']==159 and mock['prefixes']==24
assert mock['library_sha256']==sha(new/'libort_fpga.so')
assert mock['runtime_source_sha256']==sha(new/'pointwise.cc')
assert mock['transport_source_sha256']==sha(new/'qnc_transport.c')
assert mock['source_sha256']==sha(ROOT/'software/latency/test_branch512_neon_transport.py')
micro=json.loads((ROOT/'reports/fused/branch512_neon_unpack.json').read_text())
assert micro['complete'] and not micro['hardware_execution'] and micro['neon_enabled'] and micro['exact_output_and_guard_cases']==1024
paths=[p for p in new.rglob('*') if p.is_file()]
paths += [ROOT/'scripts/create_branch512_neon.py',Path(__file__),ROOT/'software/latency/test_neon_unpack.c',
          ROOT/'software/latency/test_branch512_neon_transport.py',ROOT/'reports/fused/branch512_neon_unpack.json',
          ROOT/'reports/fused/branch512_neon_mock_transport.json',ROOT/'reports/fused/branch512_neon_mock_transport.log']
proof={'complete':True,'hardware_execution':False,'arithmetic_and_program_construction_unchanged':True,
       'guarded_byte_cases':1024,'packet_checks':288,'error_checks':159,
       'library_sha256':sha(new/'libort_fpga.so'),'parent_library_sha256':sha(parent/'libort_fpga.so'),
       'notes':'Native unpack microbenchmark only. T=1 can regress; whole-model latency requires paired physical confirmation.',
       'sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}}
(ROOT/'reports/fused/branch512_neon_evidence.json').write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: unchanged arithmetic/programs, 1024 guarded byte cases, 288 packets and 159 protocol rejections')
