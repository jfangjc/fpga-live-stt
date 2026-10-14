"""Prepare a separate firmware gate and board workflow; retain qualified files."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def write(name,text):
    path=ROOT/name
    if path.exists():assert path.read_text()==text,str(path)
    else:path.write_bytes(text.encode())

text=(ROOT/'scripts/prepare_stream_firmware.py').read_text()
text=text.replace('check_stream_software','check_adaptive_software')
text=text.replace('build/stream_sim/stream_sim.sim','build/adaptive_sim/adaptive_sim.sim')
text=text.replace('PASS: 11 streamed block arithmetic','PASS: 14')
text=text.replace('stream_system','adaptive_system_v2').replace('Prototype_v3_stream','Prototype_v3_adaptive')
text=text.replace('adaptive_system_v2_implementation','adaptive_system_implementation')
text=text.replace('adaptive_system_v2_drc','adaptive_system_drc').replace('adaptive_system_v2_timing','adaptive_system_timing').replace('adaptive_system_v2_utilization','adaptive_system_utilization')
text=text.replace('asr-v3-stream','asr-v3-adaptive').replace('asr_v3_stream','asr_v3_adaptive')
text=text.replace('stream_firmware_evidence','adaptive_firmware_evidence')
text=text.replace('qn_stream_axis.sv','qn_adaptive_axis.sv').replace('qn_stream_inner.sv','qn_adaptive_inner.sv').replace('fused_depthwise_stream.sv','fused_depthwise_adaptive.sv')
text=text.replace('tb_qn_stream_axis.sv','tb_qn_adaptive_axis.sv').replace('create_stream_tb.py','create_adaptive_build.py')
text=text.replace('verification/stream-vectors','verification/adaptive-vectors')
text=text.replace("timing.update(complete=True", "registered=json.loads((reports/'registered_transport_evidence.json').read_text())\nassert registered['complete']\nfor name,value in registered['sources_and_evidence_sha256'].items():\n    assert sha(ROOT/name)==value,name\npaths += [ROOT/name for name in registered['sources_and_evidence_sha256']]\npaths += [reports/'adaptive_unit_validation.json',ROOT/'scripts/prepare_adaptive_firmware.py',ROOT/'scripts/adaptive_synth.tcl',ROOT/'scripts/adaptive_implement.tcl']\ntiming.update(adaptive_short_depthwise=True,kernel_program_cache=True,complete=True")
write('scripts/prepare_adaptive_firmware.py',text)
for source in ('finalize_stream_firmware.py','install_stream_firmware.py'):
    text=(ROOT/'scripts'/source).read_text().replace('asr-v3-stream','asr-v3-adaptive').replace('stream_firmware_evidence','adaptive_firmware_evidence')
    text=text.replace('build/stream_system/Prototype_v3_stream','build/adaptive_system_v2/Prototype_v3_adaptive')
    write('scripts/'+source.replace('stream','adaptive'),text)
text=(ROOT/'scripts/run_registered_board.sh').read_text().replace('registered_bulk_','adaptive_bulk_').replace('registered_transport_evidence','adaptive_firmware_evidence').replace('asr-v3-stream','asr-v3-adaptive')
write('scripts/run_adaptive_board.sh',text)
text=(ROOT/'software/latency/registered_benchmark.py').read_text().replace('registered_transport_evidence','adaptive_firmware_evidence').replace('asr-v3-stream','asr-v3-adaptive')
write('software/latency/adaptive_benchmark.py',text)
for source in ('validate_registered_physical.py','tune_registered_policy.py','confirm_registered_latency.py'):
    text=(ROOT/'software/latency'/source).read_text().replace('from registered_benchmark import','from adaptive_benchmark import')
    if 'confirm' in source:
        text=text.replace("summary['meets_20_percent']=", "summary['speedup_factor']=summary['cpu_p50']/summary['fpga_p50']\n        summary['meets_50_percent']=bool(summary['speedup_factor']>=2 and summary['fpga_p95']<summary['cpu_p95'])\n        summary['meets_20_percent']=")
        text=text.replace("'scope':'Warm", "'twofold_speed_acceptance':all(c['meets_50_percent'] for c in contexts),'scope':'Warm")
    write('software/latency/'+source.replace('registered','adaptive'),text)
print('Prepared isolated adaptive firmware gates, restoration and 2x benchmark helpers')
