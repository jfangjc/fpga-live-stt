"""Gate a new pair image; preserve the accepted firmware and native library."""
import hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))


def main():
    r=ROOT/'reports/fused';d=ROOT/'deployment/asr-v3-cache'
    timing=read(r/'pair_cache_system_implementation.json')
    assert timing['clock_hz']==100000000 and timing['setup_slack_ns']>=0 and timing['hold_slack_ns']>=0
    assert 'PASS:' in (r/'depthwise_channel_sim.log').read_text()
    assert 'PASS: 256 real checkpoint depthwise channels' in (r/'depthwise_model_sim.log').read_text()
    assert re.search(r'PASS: \d+ four-slot retained pair arithmetic', (r/'pair_cache_sim.log').read_text())
    drc=(r/'pair_cache_system_drc.rpt').read_text().rsplit('2. REPORT DETAILS',1)[0]
    assert not re.search(r'\|\s*(Error|Critical Warning)\s*\|',drc)
    numerical=read(r/'cache_native_oracle_validation.json');synthetic=read(r/'cache_native_synthetic.json')
    assert numerical['complete'] and synthetic['complete'] and synthetic['exact_numpy_parity']
    assert numerical['errors']['cpu']==numerical['errors']['oracle']
    assert numerical['library_sha256']==synthetic['library_sha256']==sha(ROOT/'software/ort_fpga_cache/libort_fpga.so')
    assert numerical['source_sha256']==sha(ROOT/'software/ort_fpga_cache/validate.py')
    assert numerical['graph_source_sha256']==sha(ROOT/'software/ort_fpga_cache/graph.py')
    assert synthetic['source_sha256']==sha(ROOT/'software/ort_fpga_cache/smoke.py')
    assert synthetic['arithmetic_source_sha256']==sha(ROOT/'software/latency/validate_depthwise_pair.py')
    assert 'PASS: 36912 cache slot packet' in (r/'cache_driver_protocol.log').read_text()
    assert 'PASS: four-slot transport residency' in (r/'cache_transport.log').read_text()
    assert 'PASS: 26 four-slot retained pair arithmetic' in (r/'pair_cache_sim.log').read_text()
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
    bit=ROOT/'build/pair_cache_system/Prototype_v3_pair_cache.runs/impl_1/asr_v2_top.bit'
    with zipfile.ZipFile(d/'asr_v3_cache.xsa') as z:
        names=[n for n in z.namelist() if n.endswith('.bit')];assert len(names)==1
        assert hashlib.sha256(z.read(names[0])).hexdigest()==sha(bit)
    (d/'asr-v3-cache.bit').write_bytes(bit.read_bytes())
    (d/'boot.bif').write_text('all:\n{\n  [destination_device = pl] asr-v3-cache.bit\n}\n')
    paths=[ROOT/'rtl/experimental'/n for n in ('qn_pair_cache_axis.sv','qn_pair_cache_core.v','fused_depthwise_channel.sv','fused_affine_quant.v')]
    paths += list((ROOT/'software/ort_fpga_cache').glob('*.cc'))+list((ROOT/'software/ort_fpga_cache').glob('*.c'))+list((ROOT/'software/ort_fpga_cache').glob('*.py'))
    paths += [ROOT/'software/ort_fpga_cache/libort_fpga.so',ROOT/'deployment/experimental-cache/qn_tile.ko',
              ROOT/'deployment/experimental-cache/qn_tile.c',ROOT/'deployment/experimental-cache/qn_layer_protocol.h',
              ROOT/'sim/tb_qn_pair_cache_axis.sv',ROOT/'sim/tb_fused_depthwise_channel.sv',ROOT/'sim/tb_depthwise_model.sv',ROOT/'scripts/pair_cache_system_build.tcl',
              ROOT/'scripts/pair_cache_sim.tcl',ROOT/'scripts/build_pair_cache_sources.py',ROOT/'deployment/experimental-cache/qn_cache_protocol.h',ROOT/'scripts/depthwise_channel_sim.tcl',Path(__file__),bit]
    paths += [r/n for n in ('pair_cache_system_implementation.json','pair_cache_system_timing.rpt','pair_cache_system_drc.rpt',
                            'pair_cache_system_utilization.rpt','pair_cache_sim.log','depthwise_channel_sim.log','depthwise_model_sim.log',
                            'cache_driver_protocol.log','cache_transport.log','cache_native_synthetic.json','cache_native_oracle_validation.json')]
    timing.update({'complete':True,'physical_fpga_execution_validated':False,'protected_artifacts_unchanged':True,
                   'sources_and_evidence_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}})
    (r/'cache_firmware_evidence.json').write_text(json.dumps(timing,indent=2)+'\n',encoding='utf-8')
    print('PASS: pair firmware timing, DRC, simulation, native arithmetic, protocol and protected artifact gates')


if __name__=='__main__':main()
