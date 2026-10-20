"""Gate deployment on actual primitive simulation, software parity and routing."""
import hashlib
import json
from pathlib import Path
import re
import zipfile
ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
reports=ROOT/'reports/fused';dest=ROOT/'deployment/asr-v3-chain-prefetch'
log=ROOT/'build/chain_prefetch_vector_sim/chain_prefetch_vector_sim.sim/sim_1/behav/xsim/simulate.log'
assert re.search(r'PASS: 72 retained chain and pair arithmetic',log.read_text()),'RTL sign-off incomplete'
assert not re.search(r'Fatal:|\$fatal|ERROR:',log.read_text()),'RTL simulation failed'
stall_log=ROOT/'build/chain_prefetch_stall_sim/chain_prefetch_stall_sim.sim/sim_1/behav/xsim/simulate.log'
assert 'PASS: prefetch replay stalls=' in stall_log.read_text()
assert not re.search(r'Fatal:|\$fatal|ERROR:',stall_log.read_text())
native=json.loads((reports/'chain_native_oracle.json').read_text())
assert native['complete'] and native['all_outputs_bit_exact'] and native['physical_transactions']==10
assert native['retained_boundaries']==22 and native['compiler_sha256']==sha(ROOT/'software/ort_fpga_chain/chain_graph.py')
assert native['library_sha256']==sha(ROOT/'software/ort_fpga_chain/libort_fpga.so')
numpy=json.loads((reports/'chain_numpy_oracle.json').read_text())
assert numpy['complete'] and numpy['exact_numpy_parity'] and not numpy['hardware_execution']
assert numpy['library_sha256']==native['library_sha256'] and len(numpy['cases'])==288
assert numpy['source_sha256']==sha(ROOT/'software/ort_fpga_chain/smoke_chain.py')
assert numpy['arithmetic_source_sha256']==sha(ROOT/'software/latency/validate_depthwise_pair.py')
assert all(r['bit_exact'] and r['backend']=='oracle' for r in numpy['cases'])
protocol=json.loads((reports/'chain_protocol_validation.json').read_text())
assert protocol['complete'] and protocol['driver_sha256']==sha(ROOT/'deployment/experimental-chain/qn_tile.ko')
for test in protocol['tests']:
    for name,value in test['sources_sha256'].items():assert sha(ROOT/name)==value
for name,value in protocol['headers_sha256'].items():assert sha(ROOT/name)==value
boundary=json.loads((reports/'boundary_neon_validation.json').read_text())
assert boundary['complete'] and boundary['checks']==160 and boundary['all_bit_exact']
assert boundary['library_sha256']==sha(ROOT/'software/latency/libboundary_lut.so')
assert boundary['source_sha256']==sha(ROOT/'software/latency/test_boundary_lut.py')
assert boundary['implementation_sha256']==sha(ROOT/'software/latency/boundary_lut.cc')
timing=json.loads((reports/'chain_prefetch_system_implementation.json').read_text())
assert timing['clock_hz']==100000000 and timing['setup_slack_ns']>=0 and timing['hold_slack_ns']>=0
drc=(reports/'chain_prefetch_system_drc.rpt').read_text().rsplit('2. REPORT DETAILS',1)[0]
assert not re.search(r'\|\s*(Error|Critical Warning)\s*\|',drc)
bit=ROOT/'build/chain_prefetch_system/Prototype_v3_chain_prefetch.runs/impl_1/asr_v2_top.bit'
with zipfile.ZipFile(dest/'asr_v3_chain_prefetch.xsa') as z:
    names=[n for n in z.namelist() if n.endswith('.bit')];assert len(names)==1
    assert hashlib.sha256(z.read(names[0])).hexdigest()==sha(bit)
(dest/'asr-v3-chain-prefetch.bit').write_bytes(bit.read_bytes())
(dest/'boot.bif').write_text('all:\n{\n  [destination_device = pl] asr-v3-chain-prefetch.bit\n}\n')
parent=ROOT/'deployment/asr-v3-shortwide'
(dest/'asr-v3-chain-prefetch.dts').write_text((parent/'asr-v3-shortwide.dts').read_text().replace('asr-v3-shortwide','asr-v3-chain-prefetch'))
(dest/'shell.json').write_bytes((parent/'shell.json').read_bytes())
paths=[log,stall_log,ROOT/'sim/tb_qn_chain_prefetch_stalls.sv',ROOT/'sim/tb_qn_chain_axis.sv',bit,reports/'chain_native_oracle.json',reports/'chain_prefetch_system_implementation.json',
       reports/'chain_prefetch_system_timing.rpt',reports/'chain_prefetch_system_drc.rpt',reports/'chain_prefetch_system_utilization.rpt',
       reports/'chain_numpy_oracle.json',reports/'chain_protocol_validation.json',reports/'boundary_neon_validation.json']
fixtures=json.loads((ROOT/'verification/chain-prefetch-vectors/manifest.json').read_text())
assert fixtures['independent_reference'] and fixtures['generator_sha256']==sha(ROOT/'scripts/create_chain_vectors.py')
paths += [ROOT/'scripts/create_chain_vectors.py',ROOT/'sim/tb_qn_chain_prefetch_vectors.sv',ROOT/'verification/chain-prefetch-vectors/manifest.json']
for name,value in fixtures['files_sha256'].items():
    assert sha(ROOT/name)==value
    paths.append(ROOT/name)
for folder in ('software/ort_fpga_chain','deployment/experimental-chain'):
    paths += [p for p in (ROOT/folder).glob('*') if p.is_file() and p.suffix in ('.c','.cc','.h','.py','.so','.ko')]
paths += [ROOT/'rtl/experimental'/name for name in ('qn_chain_prefetch_axis.sv','qn_chain_inner.sv','qn_short_cache_core.v',
                 'fused_depthwise_channel_wide.sv','fused_affine_quant.v')]
paths += [ROOT/'software/latency'/name for name in ('boundary_lut.py','boundary_lut.cc','libboundary_lut.so')]
timing.update(complete=True,hardware_execution=False,retained_pairs=32,retained_boundaries=22,
              warm_transactions=10,maximum_feature_frames=256,representative_corpus_qualified=False,
              sources_and_evidence_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in paths})
(reports/'chain_prefetch_firmware_evidence.json').write_text(json.dumps(timing,indent=2)+'\n')
print('PASS: retained-chain simulation, native parity, routing and image source binding')
