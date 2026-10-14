"""Bind a routed image to complete software, primitive and protocol evidence."""
import hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];reports=ROOT/'reports/fused';dest=ROOT/'deployment/asr-v3-stream'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
exec((ROOT/'scripts/check_stream_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_stream_software.py')})
logs=[ROOT/'build/stream_sim/stream_sim.sim/sim_1/behav/xsim/simulate.log',ROOT/'build/exact_requant_sim/exact_requant_sim.sim/sim_1/behav/xsim/simulate.log']
assert 'PASS: 11 streamed block arithmetic' in logs[0].read_text()
assert not any(re.search(r'Fatal:|ERROR:',p.read_text()) for p in logs)
mock=json.loads((reports/'stream_mock_transport.json').read_text())
assert mock['complete'] and not mock['hardware_execution'] and mock['all_model_prefixes_independently_exact']
assert mock['prefixes']==23 and mock['packet_checks']==552 and mock['error_checks']==92
for key,name in (('library_sha256','software/ort_fpga_stream_exact/libort_fpga.so'),('runtime_source_sha256','software/ort_fpga_stream_exact/pointwise.cc'),
                 ('transport_source_sha256','software/ort_fpga_stream_exact/qnc_transport.c')):assert mock[key]==sha(ROOT/name)
bound=json.loads((reports/'stream_accumulator_bounds.json').read_text())
assert bound['complete'] and bound['all_uint8_inputs_fit_int32'] and bound['convolutions']==200
protocol=json.loads((reports/'stream_protocol_validation.json').read_text())
assert protocol['complete'] and protocol['checks']>=177152 and protocol['driver_sha256']==sha(ROOT/'deployment/experimental-stream/qn_tile.ko')
for name,value in protocol['sources_sha256'].items():assert sha(ROOT/name)==value
for prefix,report in (('boundary_lut','boundary_neon_validation.json'),('residual_tail','residual_tail_validation.json')):
    evidence=json.loads((reports/report).read_text())
    assert evidence['complete'] and evidence['all_bit_exact']
    assert evidence['library_sha256']==sha(ROOT/f'software/latency/lib{prefix}.so')
    assert evidence['implementation_sha256']==sha(ROOT/f'software/latency/{prefix}.cc')
    assert evidence['source_sha256']==sha(ROOT/f'software/latency/test_{prefix}.py')
    if prefix=='residual_tail':assert evidence['transform_sha256']==sha(ROOT/'software/latency/residual_tail.py')
timing=json.loads((reports/'stream_system_implementation.json').read_text())
assert timing['clock_hz']==100000000 and timing['setup_slack_ns']>=0 and timing['hold_slack_ns']>=0
assert not re.search(r'\|\s*(Error|Critical Warning)\s*\|',(reports/'stream_system_drc.rpt').read_text().rsplit('2. REPORT DETAILS',1)[0])
bit=ROOT/'build/stream_system/Prototype_v3_stream.runs/impl_1/asr_v2_top.bit'
with zipfile.ZipFile(dest/'asr_v3_stream.xsa') as z:
    names=[n for n in z.namelist() if n.endswith('.bit')];assert len(names)==1 and hashlib.sha256(z.read(names[0])).hexdigest()==sha(bit)
(dest/'asr-v3-stream.bit').write_bytes(bit.read_bytes())
(dest/'boot.bif').write_text('all:\n{\n  [destination_device = pl] asr-v3-stream.bit\n}\n')
(dest/'asr-v3-stream.dts').write_text((ROOT/'deployment/asr-v3-shortwide/asr-v3-shortwide.dts').read_text().replace('asr-v3-shortwide','asr-v3-stream'))
(dest/'shell.json').write_bytes((ROOT/'deployment/asr-v3-shortwide/shell.json').read_bytes())
paths=logs+[bit,ROOT/'scripts/check_stream_software.py']
for folder in ('software/ort_fpga_stream_exact','deployment/experimental-stream'):
    paths += [p for p in (ROOT/folder).glob('*') if p.is_file() and p.suffix in ('.c','.cc','.h','.py','.so','.ko')]
paths += [ROOT/'rtl/experimental'/n for n in ('qn_stream_axis.sv','qn_stream_inner.sv','qn_stream_pw_core.v','fused_depthwise_stream.sv','fused_affine_quant_exact.sv')]
paths += [ROOT/'software/latency'/n for n in ('boundary_lut.py','boundary_lut.cc','libboundary_lut.so','residual_tail.py','residual_tail.cc','libresidual_tail.so','exact_requant_reference.py')]
paths += [reports/n for n in ('stream_transport_oracle.json','stream_mock_transport.json','stream_accumulator_bounds.json','stream_protocol_validation.json',
                             'exact_requant_integer_validation.json','boundary_neon_validation.json','residual_tail_validation.json','stream_system_implementation.json','stream_system_timing.rpt','stream_system_drc.rpt','stream_system_utilization.rpt')]
paths += [ROOT/'sim/tb_qn_stream_axis.sv',ROOT/'sim/tb_exact_requant.sv',ROOT/'scripts/create_stream_tb.py',ROOT/'scripts/test_exact_requant.py']
paths += list((ROOT/'verification/stream-vectors').glob('*'))+[ROOT/'verification/exact-requant/quant.mem']
timing.update(complete=True,hardware_execution=False,retained_pairs=100,retained_boundaries=77,warm_transactions=23,
              weight_updates_per_inference=200,weight_transfers_inside_timing=True,maximum_feature_frames=256,
              representative_corpus_qualified=False,sources_and_evidence_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in paths})
(reports/'stream_firmware_evidence.json').write_text(json.dumps(timing,indent=2)+'\n')
print('PASS: exact software arithmetic, primitive RTL, packet validation, timing/DRC and bitstream binding')
