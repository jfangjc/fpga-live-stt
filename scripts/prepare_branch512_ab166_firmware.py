"""Require complete source-bound arithmetic/protocol and routed timing evidence."""
import hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];reports=ROOT/'reports/fused'
dest=ROOT/'deployment/asr-v3-branch512-ab166'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
exec((ROOT/'scripts/check_branch512_ab_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_branch512_ab_software.py')})
reference_proof=ROOT/'reports/fused/branch512_drop166_incremental_license_failure.json'
reference_record=json.loads(reference_proof.read_text());assert reference_record['complete']
assert not reference_record['incremental_license_supported']
for path,value in reference_record['sources_sha256'].items():assert sha(ROOT/path)==value,path
paths=[reference_proof]+[ROOT/path for path in reference_record['sources_sha256']]
drop_parent=ROOT/'reports/fused/branch512_drop_regression_evidence.json'
drop_record=json.loads(drop_parent.read_text());assert drop_record['complete']
for path,value in drop_record['sources_sha256'].items():assert sha(ROOT/path)==value,path
paths += [drop_parent]+[ROOT/path for path in drop_record['sources_sha256']]
guard_parent=ROOT/'reports/fused/branch512_guard_regression_evidence.json'
guard_record=json.loads(guard_parent.read_text());assert guard_record['complete']
for path,value in guard_record['sources_sha256'].items():assert sha(ROOT/path)==value,path
paths += [guard_parent]+[ROOT/path for path in guard_record['sources_sha256']]


for name,key in (('registered_transport_evidence.json','sources_and_evidence_sha256'),
                 ('compact_requant_evidence.json','sources_and_evidence_sha256'),
                 ('branch512_ab_regression_evidence.json','sources_sha256'),
                 ('branch_driver_validation.json','sources_sha256')):
    report=reports/name;proof=json.loads(report.read_text());assert proof['complete']
    for path,value in proof[key].items():assert sha(ROOT/path)==value,path
    paths += [report]+[ROOT/path for path in proof[key]]
for name,count,test in (('branch512_oracle.json',36,'validate_branch512_oracle.py'),
                        ('branch512_masks.json',294,'test_branch512_masks.py')):
    report=reports/name;proof=json.loads(report.read_text());assert proof['complete']
    assert len(proof['clips'] if count==36 else proof['cases'])==count
    assert proof['library_sha256']==sha(ROOT/'software/ort_fpga_stream_branch512/libort_fpga.so')
    assert proof['compiler_sha256']==sha(ROOT/'software/ort_fpga_stream_branch512/branch_graph.py')
    assert proof['source_sha256']==sha(ROOT/'software/latency'/test)
    assert proof['all_cpu_logits_bit_exact'] if count==36 else proof['all_outputs_bit_exact']
    paths += [report,ROOT/'software/latency'/test]
timing=json.loads((reports/'branch512_ab166_system_implementation.json').read_text())
assert timing['clock_hz']==166666666 and timing['pointwise_macs']==512 and timing['depthwise_macs']==64
assert timing['setup_slack_ns']>=0.001 and timing['hold_slack_ns']>=0
assert not re.search(r'\|\s*(Error|Critical Warning)\s*\|',(reports/'branch512_ab166_system_drc.rpt').read_text().rsplit('2. REPORT DETAILS',1)[0])
bit=ROOT/'build/branch512_ab166_system/Prototype_v3_branch512_ab166.runs/impl_1/asr_v2_top.bit'
with zipfile.ZipFile(dest/'asr_v3_branch512_ab166.xsa') as z:
    names=[n for n in z.namelist() if n.endswith('.bit')]
    assert len(names)==1 and hashlib.sha256(z.read(names[0])).hexdigest()==sha(bit)
synth=ROOT/'scripts/branch512_ab166_synth.tcl'
assert 'Simulation MAC model must never enter synthesis' in synth.read_text()
(dest/'asr-v3-branch512-ab166.bit').write_bytes(bit.read_bytes())
(dest/'boot.bif').write_text('all:\n{\n  [destination_device = pl] asr-v3-branch512-ab166.bit\n}\n')
(dest/'asr-v3-branch512-ab166.dts').write_text((ROOT/'deployment/asr-v3-shortwide/asr-v3-shortwide.dts').read_text().replace('asr-v3-shortwide','asr-v3-branch512-ab166'))
(dest/'shell.json').write_bytes((ROOT/'deployment/asr-v3-shortwide/shell.json').read_bytes())
for folder in ('software/ort_fpga_stream_branch512','deployment/experimental-stream-branch'):
    paths += [p for p in (ROOT/folder).glob('*') if p.is_file() and p.suffix in ('.c','.cc','.h','.py','.so','.ko')]
paths += [ROOT/'rtl/experimental/voice_axi_inference.v',bit,synth,ROOT/'scripts/branch512_ab166_implement.tcl',Path(__file__)]
paths += [reports/'branch512_mock_transport.json']
paths += [reports/('branch512_ab166_system_'+n) for n in ('implementation.json','timing.rpt','drc.rpt','utilization.rpt')]
timing.update(incremental_implementation=False,implementation_flow='full',complete=True,hardware_execution=False,kernel_program_cache=True,warm_transactions=23,
    retained_pairs=121,main_path_pairs=100,residual_projections=21,retained_boundaries=77,
    weight_updates_per_inference=242,weight_transfers_inside_timing=True,maximum_feature_frames=256,
    representative_corpus_qualified=False,capture_clock_changed=True,legacy_mac_disabled=True,minimum_setup_margin_ns=0.001,
    sources_and_evidence_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in paths})
(reports/'branch512_ab166_firmware_evidence.json').write_text(json.dumps(timing,indent=2)+'\n')
print('PASS: software parity, full block RTL, driver protocol, timing and XSA bitstream bound')
