"""Gate and bind the isolated routed firmware before binary conversion."""
import hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    report=ROOT/'reports/fused'
    result=json.loads((report/'bulk_system_implementation.json').read_text())
    assert result['setup_slack_ns']>=0 and result['hold_slack_ns']>=0
    drc=(report/'bulk_system_drc.rpt').read_text().rsplit('2. REPORT DETAILS',1)[0]
    assert not re.search(r'\|\s*(Error|Critical Warning)\s*\|',drc)
    assert 'PASS: 20 paired-group raw/quantized/bulk arithmetic' in (report/'bulk_cached_sim_watchdog.log').read_text()
    assert 'PASS: 13 bulk overflow' in (report/'bulk_errors_sim.log').read_text()
    assert 'PASS: 204800 retained-input' in (report/'bulk_driver_protocol.log').read_text()
    assert 'PASS: 1024 independent affine' in (report/'affine_quant_sim.log').read_text()
    assert 'PASS: 305152 raw bounds checks' in (report/'bulk_driver_protocol.log').read_text()
    oracle=json.loads((report/'bulk_oracle_regression.json').read_text())
    assert oracle['all_transcripts_identical']
    assert oracle['library_sha256']==sha(ROOT/'software/ort_fpga_bulk/libort_fpga.so')
    assert 'PASS: 130560 independently indexed bytes' in (report/'quant_vector_transpose.log').read_text()
    protected=json.loads((report/'quant_protected_before.json').read_text(encoding='utf-8-sig'))
    for path,digest in protected.items():assert sha(ROOT/path).upper()==digest.upper(),path
    directory=ROOT/'deployment/asr-v3-bulk'
    bit=ROOT/'build/bulk_system/Prototype_v3_bulk.runs/impl_1/asr_v2_top.bit'
    with zipfile.ZipFile(directory/'asr_v3_bulk.xsa') as archive:
        items=[name for name in archive.namelist() if name.endswith('.bit')]
        assert len(items)==1
        assert hashlib.sha256(archive.read(items[0])).hexdigest()==sha(bit)
    (directory/'asr-v3-bulk.bit').write_bytes(bit.read_bytes())
    (directory/'boot.bif').write_text('all:\n{\n  [destination_device = pl] asr-v3-bulk.bit\n}\n')
    files=[Path(__file__),ROOT/'rtl/experimental/qn_bulk_axis.v',ROOT/'rtl/experimental/fused_affine_quant.v',
           ROOT/'sim/tb_qn_bulk_axis.sv',ROOT/'sim/tb_fused_affine_quant.sv',
           directory/'asr-v3-bulk.bit',directory/'asr_v3_bulk.xsa',
           directory/'asr-v3-bulk.dts',directory/'asr-v3-bulk.dtbo',directory/'shell.json',directory/'activate.sh',ROOT/'deployment/experimental-bulk/qn_tile_uapi.h',ROOT/'software/ort_fpga_bulk/qnc.h',ROOT/'scripts/bulk_system_build.tcl',ROOT/'scripts/vivado_four_threads.tcl',
           ROOT/'deployment/experimental-bulk/qn_tile.c',
           ROOT/'deployment/experimental-bulk/qn_layer_protocol.h',
           ROOT/'deployment/experimental-bulk/qn_tile.ko',
           ROOT/'software/ort_fpga_bulk/pointwise.cc',ROOT/'software/ort_fpga_bulk/qnc_transport.c',
           ROOT/'software/ort_fpga_bulk/libort_fpga.so',
           report/'bulk_driver_protocol.log',
           report/'quant_vector_transpose.log',
           report/'bulk_system_timing.rpt',report/'bulk_system_drc.rpt',
           report/'bulk_system_utilization.rpt',report/'bulk_cached_sim_watchdog.log',
           report/'bulk_errors_sim.log',ROOT/'sim/tb_qn_bulk_errors.sv',report/'affine_quant_sim.log',report/'bulk_oracle_regression.json']
    result['source_evidence_sha256']={p.relative_to(ROOT).as_posix():sha(p) for p in files}
    result['protected_artifacts_unchanged']=True
    result['physical_fpga_execution_validated']=False
    (report/'bulk_firmware_evidence.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS: integrated timing, DRC, simulations, accuracy regression, bit/XSA identity and protected artifacts')


if __name__=='__main__':main()
