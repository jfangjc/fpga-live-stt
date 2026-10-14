"""Bind wider-depthwise firmware to timing, arithmetic and preserved parent evidence."""
import hashlib,json,re,runpy,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
runpy.run_path(str(ROOT/'scripts/check_short_wide_build.py'))
r=ROOT/'reports/fused';d=ROOT/'deployment/asr-v3-shortwide'
timing=read(r/'short_wide_system_implementation.json')
assert timing['clock_hz']==100000000 and timing['depthwise_macs']==64 and timing['pointwise_macs']==512
assert timing['setup_slack_ns']>=0 and timing['hold_slack_ns']>=0
drc=(r/'short_wide_system_drc.rpt').read_text().rsplit('2. REPORT DETAILS',1)[0]
assert not re.search(r'\|\s*(Error|Critical Warning)\s*\|',drc)
native=read(r/'shortwide_native_oracle_validation.json');synthetic=read(r/'shortwide_native_synthetic.json')
assert native['complete'] and native['retained_pairs']==32 and native['all_prefix_transcripts_exact']
assert native['diagnostic_wer_delta_percentage_points']<=1 and synthetic['complete'] and synthetic['exact_numpy_parity']
runtime=ROOT/'software/ort_fpga_shortwide'
assert native['library_sha256']==synthetic['library_sha256']==sha(runtime/'libort_fpga.so')
assert native['source_sha256']==sha(runtime/'validate.py') and native['graph_source_sha256']==sha(runtime/'graph.py')
assert native['selection_sha256']==sha(runtime/'selection.json') and synthetic['source_sha256']==sha(runtime/'smoke.py')
assert synthetic['arithmetic_source_sha256']==sha(ROOT/'software/latency/validate_depthwise_pair.py')
bit=ROOT/'build/short_wide_system/Prototype_v3_short_wide.runs/impl_1/asr_v2_top.bit'
with zipfile.ZipFile(d/'asr_v3_shortwide.xsa') as z:
    names=[n for n in z.namelist() if n.endswith('.bit')];assert len(names)==1
    assert hashlib.sha256(z.read(names[0])).hexdigest()==sha(bit)
(d/'asr-v3-shortwide.bit').write_bytes(bit.read_bytes())
(d/'boot.bif').write_bytes(b'all:\n{\n  [destination_device = pl] asr-v3-shortwide.bit\n}\n')
freeze=read(r/'shortwide_source_freeze.json')
paths=[ROOT/name for name in freeze['sources_sha256']]
paths += [p for p in runtime.glob('*') if p.is_file()]
paths += [ROOT/'scripts'/name for name in ('check_short_wide_build.py','short_wide_implement.tcl','prepare_short_wide_firmware.py','install_short_wide_firmware.sh','run_short_wide_physical.sh','bind_short_wide_binary.py')]
paths += [d/name for name in ('asr-v3-shortwide.dts','asr-v3-shortwide.dtbo','shell.json','activate.sh')]
paths += [r/name for name in ('shortwide_source_freeze.json','short_wide_sim.log','short_wide_system_implementation.json','short_wide_system_timing.rpt','short_wide_system_drc.rpt','short_wide_system_utilization.rpt','shortwide_native_synthetic.json','shortwide_native_oracle_validation.json')]
paths += [ROOT/'software/latency'/name for name in ('confirm_short_wide_schedule.py','short_wide_resident.py','check_short_wide_resident.py')]
paths += [ROOT/'scripts/create_short_wide_resident.py',ROOT/'scripts/verify_short_wide_restoration.py',bit]
timing.update(complete=True,physical_fpga_execution_validated=False,protected_artifacts_unchanged=True,
              native_library_reused=True,driver_reused=True,retained_pairs=32,accelerated_convolutions=64,
              maximum_feature_frames=256,sources_and_evidence_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in set(paths)})
(r/'shortwide_firmware_evidence.json').write_text(json.dumps(timing,indent=2)+'\n')
print('PASS: wider firmware implementation, numerical checks and source bindings')
