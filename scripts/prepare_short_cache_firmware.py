"""Gate a new pair image; preserve the accepted firmware and native library."""
import hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))


def main():
    r=ROOT/'reports/fused';d=ROOT/'deployment/asr-v3-shortcache'
    timing=read(r/'short_cache_system_implementation.json')
    assert timing['clock_hz']==100000000 and timing['setup_slack_ns']>=0 and timing['hold_slack_ns']>=0
    assert 'PASS:' in (r/'depthwise_channel_sim.log').read_text()
    assert 'PASS: 256 real checkpoint depthwise channels' in (r/'depthwise_model_sim.log').read_text()
    assert re.search(r'PASS: \d+ short-cache retained pair arithmetic', (r/'short_cache_sim.log').read_text())
    drc=(r/'short_cache_system_drc.rpt').read_text().rsplit('2. REPORT DETAILS',1)[0]
    assert not re.search(r'\|\s*(Error|Critical Warning)\s*\|',drc)
    numerical=read(r/'shortcache_native_oracle_validation.json');synthetic=read(r/'shortcache_native_synthetic.json')
    assert numerical['complete'] and synthetic['complete'] and synthetic['exact_numpy_parity']
    assert numerical['all_prefix_transcripts_exact'] and numerical['diagnostic_wer_delta_percentage_points']<=1
    assert numerical['retained_pairs']==32
    assert numerical['library_sha256']==synthetic['library_sha256']==sha(ROOT/'software/ort_fpga_shortcache/libort_fpga.so')
    assert numerical['source_sha256']==sha(ROOT/'software/ort_fpga_shortcache/validate.py')
    assert numerical['graph_source_sha256']==sha(ROOT/'software/ort_fpga_shortcache/graph.py')
    assert synthetic['source_sha256']==sha(ROOT/'software/ort_fpga_shortcache/smoke.py')
    assert synthetic['arithmetic_source_sha256']==sha(ROOT/'software/latency/validate_depthwise_pair.py')
    assert 'PASS: 62144 short-cache packet' in (r/'shortcache_driver_protocol.log').read_text()
    assert 'PASS: 32-slot transport residency' in (r/'shortcache_transport.log').read_text()
    assert 'PASS: 64 short-cache retained pair arithmetic' in (r/'short_cache_sim.log').read_text()
    previous=read(r/'pair_firmware_evidence.json')
    for name in ('rtl/experimental/fused_depthwise_channel.sv','rtl/experimental/fused_affine_quant.v'):
        assert sha(ROOT/name)==previous['sources_and_evidence_sha256'][name]
    pair=read(r/'pair_physical_validation.json')
    for name,key in [('software/ort_fpga_pair/libort_fpga.so','library_sha256'),
                     ('deployment/experimental-pair/qn_tile.ko','driver_sha256'),
                     ('deployment/asr-v3-pair/asr-v3-pair.bit.bin','firmware_sha256')]:
        assert sha(ROOT/name)==pair[key]
    accepted=read(r/'short_half_second_deployment.json')
    for p,key in [('software/ort_fpga_bulk/libort_fpga.so','library_sha256'),
                  ('deployment/asr-v3-bulk/asr-v3-bulk.bit.bin','firmware_sha256')]:
        assert sha(ROOT/p)==accepted[key]
    cache=read(r/'cache_physical_validation.json')
    for name,key in [('software/ort_fpga_cache/libort_fpga.so','library_sha256'),
                     ('deployment/experimental-cache/qn_tile.ko','driver_sha256'),
                     ('deployment/asr-v3-cache/asr-v3-cache.bit.bin','firmware_sha256')]:
        assert sha(ROOT/name)==cache[key]
    selection=ROOT/'software/ort_fpga_shortcache/selection.json'
    assert numerical['selection_sha256']==sha(selection)
    bit=ROOT/'build/short_cache_system/Prototype_v3_short_cache.runs/impl_1/asr_v2_top.bit'
    with zipfile.ZipFile(d/'asr_v3_shortcache.xsa') as z:
        names=[n for n in z.namelist() if n.endswith('.bit')];assert len(names)==1
        assert hashlib.sha256(z.read(names[0])).hexdigest()==sha(bit)
    (d/'asr-v3-shortcache.bit').write_bytes(bit.read_bytes())
    (d/'boot.bif').write_text('all:\n{\n  [destination_device = pl] asr-v3-shortcache.bit\n}\n')
    paths=[ROOT/'rtl/experimental'/n for n in ('qn_short_cache_axis.sv','qn_short_cache_core.v','fused_depthwise_channel.sv','fused_affine_quant.v')]
    paths += list((ROOT/'software/ort_fpga_shortcache').glob('*.cc'))+list((ROOT/'software/ort_fpga_shortcache').glob('*.c'))+list((ROOT/'software/ort_fpga_shortcache').glob('*.py'))
    paths += [ROOT/'software/ort_fpga_shortcache/libort_fpga.so',ROOT/'deployment/experimental-shortcache/qn_tile.ko',
              ROOT/'deployment/experimental-shortcache/qn_tile.c',ROOT/'deployment/experimental-shortcache/qn_layer_protocol.h',
              ROOT/'sim/tb_qn_short_cache_axis.sv',ROOT/'sim/tb_fused_depthwise_channel.sv',ROOT/'sim/tb_depthwise_model.sv',ROOT/'scripts/short_cache_system_build.tcl',
              ROOT/'scripts/short_cache_sim.tcl',ROOT/'scripts/build_short_cache_sources.py',ROOT/'deployment/experimental-shortcache/qn_cache_protocol.h',ROOT/'scripts/depthwise_channel_sim.tcl',Path(__file__),bit,selection,
              ROOT/'scripts/short_cache_synth.tcl',ROOT/'scripts/short_cache_implement.tcl',ROOT/'scripts/generate_short_cache_tb.py',
              ROOT/'software/ort_fpga_shortcache/qnc.h',
              d/'asr-v3-shortcache.dts',d/'asr-v3-shortcache.dtbo',d/'shell.json',d/'activate.sh',
              ROOT/'scripts/check_shortcache_software.py',ROOT/'scripts/install_short_cache_firmware.sh',
              ROOT/'scripts/run_short_cache_physical.sh',ROOT/'scripts/verify_short_cache_restoration.py']
    paths += [r/n for n in ('short_cache_system_implementation.json','short_cache_system_timing.rpt','short_cache_system_drc.rpt',
                            'short_cache_system_utilization.rpt','short_cache_sim.log','depthwise_channel_sim.log','depthwise_model_sim.log',
                            'shortcache_driver_protocol.log','shortcache_transport.log','shortcache_native_synthetic.json','shortcache_native_oracle_validation.json',
                            'shortcache_selection_screen.json','shortcache_selection_graph_source.py','shortcache_initial_accuracy.json')]
    timing.update({'complete':True,'physical_fpga_execution_validated':False,'protected_artifacts_unchanged':True,
                   'sources_and_evidence_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}})
    (r/'shortcache_firmware_evidence.json').write_text(json.dumps(timing,indent=2)+'\n',encoding='utf-8')
    print('PASS: pair firmware timing, DRC, simulation, native arithmetic, protocol and protected artifact gates')


if __name__=='__main__':main()
