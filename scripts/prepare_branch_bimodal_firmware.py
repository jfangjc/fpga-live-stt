"""Require complete source-bound arithmetic/protocol and routed timing evidence."""
import hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];reports=ROOT/'reports/fused'
dest=ROOT/'deployment/asr-v3-branch-bimodal'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
exec((ROOT/'scripts/check_branch_bimodal_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_branch_bimodal_software.py')})
paths=[]
for name,key in (('registered_transport_evidence.json','sources_and_evidence_sha256'),
                 ('compact_requant_evidence.json','sources_and_evidence_sha256'),
                 ('branch_bimodal_regression_evidence.json','sources_sha256'),
                 ('branch_driver_validation.json','sources_sha256')):
    report=reports/name;proof=json.loads(report.read_text());assert proof['complete']
    for path,value in proof[key].items():assert sha(ROOT/path)==value,path
    paths += [report]+[ROOT/path for path in proof[key]]
for name,count,test in (('branch_backend_oracle.json',36,'validate_branch_backend_oracle.py'),
                        ('branch_backend_masks.json',294,'test_branch_backend_masks.py')):
    report=reports/name;proof=json.loads(report.read_text());assert proof['complete']
    assert len(proof['clips'] if count==36 else proof['cases'])==count
    assert proof['library_sha256']==sha(ROOT/'software/ort_fpga_stream_branch_transport/libort_fpga.so')
    assert proof['compiler_sha256']==sha(ROOT/'software/ort_fpga_stream_branch_transport/branch_graph.py')
    assert proof['source_sha256']==sha(ROOT/'software/latency'/test)
    assert proof['all_cpu_logits_bit_exact'] if count==36 else proof['all_outputs_bit_exact']
    paths += [report,ROOT/'software/latency'/test]
timing=json.loads((reports/'branch_bimodal_system_implementation.json').read_text())
assert timing['clock_hz']==100000000 and timing['pointwise_macs']==1024 and timing['depthwise_macs']==64
assert timing['setup_slack_ns']>=0 and timing['hold_slack_ns']>=0
assert not re.search(r'\|\s*(Error|Critical Warning)\s*\|',(reports/'branch_bimodal_system_drc.rpt').read_text().rsplit('2. REPORT DETAILS',1)[0])
bit=ROOT/'build/branch_bimodal_system/Prototype_v3_branch_bimodal.runs/impl_1/asr_v2_top.bit'
with zipfile.ZipFile(dest/'asr_v3_branch_bimodal.xsa') as z:
    names=[n for n in z.namelist() if n.endswith('.bit')]
    assert len(names)==1 and hashlib.sha256(z.read(names[0])).hexdigest()==sha(bit)
synth=ROOT/'scripts/branch_bimodal_synth.tcl'
assert 'Simulation MAC model must never enter synthesis' in synth.read_text()
(dest/'asr-v3-branch-bimodal.bit').write_bytes(bit.read_bytes())
(dest/'boot.bif').write_text('all:\n{\n  [destination_device = pl] asr-v3-branch-bimodal.bit\n}\n')
(dest/'asr-v3-branch-bimodal.dts').write_text((ROOT/'deployment/asr-v3-shortwide/asr-v3-shortwide.dts').read_text().replace('asr-v3-shortwide','asr-v3-branch-bimodal'))
(dest/'shell.json').write_bytes((ROOT/'deployment/asr-v3-shortwide/shell.json').read_bytes())
for folder in ('software/ort_fpga_stream_branch_transport','deployment/experimental-stream-branch'):
    paths += [p for p in (ROOT/folder).glob('*') if p.is_file() and p.suffix in ('.c','.cc','.h','.py','.so','.ko')]
paths += [bit,synth,ROOT/'scripts/branch_bimodal_implement.tcl',Path(__file__)]
paths += [reports/'branch_mock_transport.json']
paths += [reports/('branch_bimodal_system_'+n) for n in ('implementation.json','timing.rpt','drc.rpt','utilization.rpt')]
timing.update(complete=True,hardware_execution=False,kernel_program_cache=True,warm_transactions=23,
    retained_pairs=121,main_path_pairs=100,residual_projections=21,retained_boundaries=77,
    weight_updates_per_inference=242,weight_transfers_inside_timing=True,maximum_feature_frames=256,
    representative_corpus_qualified=False,
    sources_and_evidence_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in paths})
(reports/'branch_bimodal_firmware_evidence.json').write_text(json.dumps(timing,indent=2)+'\n')
print('PASS: software parity, full block RTL, driver protocol, timing and XSA bitstream bound')
