"""Gate a new pair image; preserve the accepted firmware and native library."""
import hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))


def main():
    r=ROOT/'reports/fused';d=ROOT/'deployment/asr-v3-pair'
    timing=read(r/'fused_system_implementation.json')
    assert timing['clock_hz']==100000000 and timing['setup_slack_ns']>=0 and timing['hold_slack_ns']>=0
    assert 'PASS:' in (r/'depthwise_channel_sim.log').read_text()
    assert 'PASS: 256 real checkpoint depthwise channels' in (r/'depthwise_model_sim.log').read_text()
    assert re.search(r'PASS: \d+ fused depthwise/pointwise arithmetic', (r/'fused_pair_sim.log').read_text())
    drc=(r/'fused_system_drc.rpt').read_text().rsplit('2. REPORT DETAILS',1)[0]
    assert not re.search(r'\|\s*(Error|Critical Warning)\s*\|',drc)
    numerical=read(r/'pair_native_oracle_validation.json');synthetic=read(r/'pair_native_synthetic.json')
    assert numerical['complete'] and synthetic['complete'] and synthetic['exact_numpy_parity']
    assert numerical['errors']['cpu']==numerical['errors']['oracle']
    assert numerical['library_sha256']==synthetic['library_sha256']==sha(ROOT/'software/ort_fpga_pair/libort_fpga.so')
    assert numerical['source_sha256']==sha(ROOT/'software/ort_fpga_pair/validate.py')
    assert numerical['graph_source_sha256']==sha(ROOT/'software/ort_fpga_pair/graph.py')
    assert synthetic['source_sha256']==sha(ROOT/'software/ort_fpga_pair/smoke.py')
    assert synthetic['arithmetic_source_sha256']==sha(ROOT/'software/latency/validate_depthwise_pair.py')
    protocol=(r/'pair_driver_protocol.log').read_text()
    for marker in ('104448 paired packet','305152 raw bounds','204800 retained-input'):
        assert 'PASS: '+marker in protocol
    # The copied pointwise engine differs only in its top-level module name.
    assert (ROOT/'rtl/experimental/qn_fused_core.v').read_text()==(ROOT/'rtl/experimental/qn_bulk_axis.v').read_text().replace('module qn_cached_axis #','module qn_bulk_core #')
    accepted=read(r/'short_half_second_deployment.json')
    for p,key in [('software/ort_fpga_bulk/libort_fpga.so','library_sha256'),
                  ('deployment/asr-v3-bulk/asr-v3-bulk.bit.bin','firmware_sha256')]:
        assert sha(ROOT/p)==accepted[key]
    bit=ROOT/'build/fused_system/Prototype_v3_fused_pair.runs/impl_1/asr_v2_top.bit'
    with zipfile.ZipFile(d/'asr_v3_pair.xsa') as z:
        names=[n for n in z.namelist() if n.endswith('.bit')];assert len(names)==1
        assert hashlib.sha256(z.read(names[0])).hexdigest()==sha(bit)
    (d/'asr-v3-pair.bit').write_bytes(bit.read_bytes())
    (d/'boot.bif').write_text('all:\n{\n  [destination_device = pl] asr-v3-pair.bit\n}\n')
    paths=[ROOT/'rtl/experimental'/n for n in ('qn_fused_axis.sv','qn_fused_core.v','fused_depthwise_channel.sv','fused_affine_quant.v')]
    paths += list((ROOT/'software/ort_fpga_pair').glob('*.cc'))+list((ROOT/'software/ort_fpga_pair').glob('*.c'))+list((ROOT/'software/ort_fpga_pair').glob('*.py'))
    paths += [ROOT/'software/ort_fpga_pair/libort_fpga.so',ROOT/'deployment/experimental-pair/qn_tile.ko',
              ROOT/'deployment/experimental-pair/qn_tile.c',ROOT/'deployment/experimental-pair/qn_layer_protocol.h',
              ROOT/'sim/tb_qn_fused_axis.sv',ROOT/'sim/tb_fused_depthwise_channel.sv',ROOT/'sim/tb_depthwise_model.sv',ROOT/'scripts/fused_system_build.tcl',
              ROOT/'scripts/fused_pair_sim.tcl',ROOT/'scripts/depthwise_channel_sim.tcl',Path(__file__),bit]
    paths += [r/n for n in ('fused_system_implementation.json','fused_system_timing.rpt','fused_system_drc.rpt',
                            'fused_system_utilization.rpt','fused_pair_sim.log','depthwise_channel_sim.log','depthwise_model_sim.log',
                            'pair_driver_protocol.log','pair_native_synthetic.json','pair_native_oracle_validation.json')]
    timing.update({'complete':True,'physical_fpga_execution_validated':False,'protected_artifacts_unchanged':True,
                   'sources_and_evidence_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}})
    (r/'pair_firmware_evidence.json').write_text(json.dumps(timing,indent=2)+'\n',encoding='utf-8')
    print('PASS: pair firmware timing, DRC, simulation, native arithmetic, protocol and protected artifact gates')


if __name__=='__main__':main()
