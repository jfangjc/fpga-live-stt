"""Bind the separate transport to its unchanged, qualified FPGA firmware."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];reports=ROOT/'reports/fused'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
proof=json.loads((reports/'stream_firmware_evidence.json').read_text())
assert proof['complete'] and proof['deployment_conversion_complete']
for name,value in proof['sources_and_evidence_sha256'].items():assert sha(ROOT/name)==value,name
oracle=json.loads((reports/'registered_transport_oracle.json').read_text())
assert oracle['complete'] and not oracle['hardware_execution']
assert oracle['all_cpu_logits_bit_exact'] and oracle['all_diagnostic_transcripts_equal']
assert oracle['retained_pairs']==100 and oracle['transactions']==23 and len(oracle['clips'])==36
for key,name in (('library_sha256','libort_fpga.so'),('runtime_source_sha256','pointwise.cc'),
                 ('pair_compiler_sha256','pair_graph.py'),('chain_compiler_sha256','stream_graph.py')):
    assert oracle[key]==sha(ROOT/'software/ort_fpga_stream_registered'/name)
mock=json.loads((reports/'registered_mock_transport.json').read_text())
assert mock['complete'] and not mock['hardware_execution'] and mock['all_model_prefixes_independently_exact']
assert mock['packet_checks']==552 and mock['error_checks']==92
assert mock['library_sha256']==oracle['library_sha256']
assert mock['runtime_source_sha256']==oracle['runtime_source_sha256']
assert mock['transport_source_sha256']==sha(ROOT/'software/ort_fpga_stream_registered/qnc_transport.c')
assert 'PASS: 177152' in (reports/'registered_protocol_test.log').read_text()
assert 'PASS: 232130' in (reports/'registered_bounds_test.log').read_text()
driver=ROOT/'deployment/experimental-stream-registered/qn_tile.ko'
vermagic=re.search(rb'vermagic=([^\x00]+)',driver.read_bytes()).group(1).decode()
assert vermagic.startswith('6.8.0-1036-xilinx ')
paths=[reports/n for n in ('registered_transport_oracle.json','registered_mock_transport.json','registered_protocol_test.log','registered_bounds_test.log')]
for folder in ('software/ort_fpga_stream_registered','deployment/experimental-stream-registered'):
    paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.c','.cc','.h','.py','.sh','.so','.ko'))
paths.extend(ROOT/'software/latency'/n for n in ('test_registered_physical.py','test_registered_transport.py','validate_registered_oracle.py','registered_benchmark.py'))
paths.extend((Path(__file__).resolve(),ROOT/'scripts/run_registered_board.sh'))
proof['sources_and_evidence_sha256'].update({p.relative_to(ROOT).as_posix():sha(p) for p in paths})
proof.update(kernel_program_cache=True,driver_vermagic=vermagic,hardware_execution=False,
             physical_execution=False,scope='Build and software evidence; physical qualification is recorded separately',
             dma_ownership_reference='https://www.kernel.org/doc/html/latest/core-api/dma-api.html')
(reports/'registered_transport_evidence.json').write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: unchanged routed FPGA, exact oracle, mock packets and registered kernel ABI bound')
