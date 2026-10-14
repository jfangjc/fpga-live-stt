"""Gate and bind the isolated routed firmware before binary conversion."""
import hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    report=ROOT/'reports/fused'
    result=json.loads((report/'quant_system_implementation.json').read_text())
    assert result['setup_slack_ns']>=0 and result['hold_slack_ns']>=0
    drc=(report/'quant_system_drc.rpt').read_text().rsplit('2. REPORT DETAILS',1)[0]
    assert not re.search(r'\|\s*(Error|Critical Warning)\s*\|',drc)
    assert 'PASS: 97 raw and fused quantized' in (report/'quant_cached_sim_extended.log').read_text()
    assert 'PASS: 1024 independent affine' in (report/'affine_quant_sim.log').read_text()
    assert 'PASS: 305152 raw bounds checks' in (report/'quant_driver_protocol.log').read_text()
    oracle=json.loads((report/'quantized-pointwise-oracle-regression.json').read_text())
    assert oracle['all_transcripts_identical']
    assert oracle['library_sha256']==sha(ROOT/'software/ort_fpga/libort_fpga.so')
    assert 'PASS: 130560 independently indexed bytes' in (report/'quant_vector_transpose.log').read_text()
    protected=json.loads((report/'quant_protected_before.json').read_text(encoding='utf-8-sig'))
    for path,digest in protected.items():assert sha(ROOT/path).upper()==digest.upper(),path
    directory=ROOT/'deployment/asr-v3-quant'
    bit=ROOT/'build/quant_system/Prototype_v3_quant.runs/impl_1/asr_v2_top.bit'
    with zipfile.ZipFile(directory/'asr_v3_quant.xsa') as archive:
        items=[name for name in archive.namelist() if name.endswith('.bit')]
        assert len(items)==1
        assert hashlib.sha256(archive.read(items[0])).hexdigest()==sha(bit)
    (directory/'asr-v3-quant.bit').write_bytes(bit.read_bytes())
    (directory/'boot.bif').write_text('all:\n{\n  [destination_device = pl] asr-v3-quant.bit\n}\n')
    files=[ROOT/'rtl/experimental/qn_quant_axis.v',ROOT/'rtl/experimental/fused_affine_quant.v',
           ROOT/'sim/tb_qn_quant_axis.sv',ROOT/'sim/tb_fused_affine_quant.sv',
           directory/'asr-v3-quant.bit',directory/'asr_v3_quant.xsa',
           directory/'asr-v3-quant.dts',directory/'asr-v3-quant.dtbo',directory/'shell.json',
           ROOT/'deployment/experimental-quant/qn_tile.c',
           ROOT/'deployment/experimental-quant/qn_layer_protocol.h',
           ROOT/'deployment/experimental-quant/qn_tile.ko',
           ROOT/'software/ort_fpga/pointwise.cc',ROOT/'software/ort_fpga/qnc_transport.c',
           ROOT/'software/ort_fpga/libort_fpga.so',
           report/'quant_driver_protocol.log',
           report/'quant_vector_transpose.log',
           report/'quant_system_timing.rpt',report/'quant_system_drc.rpt',
           report/'quant_system_utilization.rpt',report/'quant_cached_sim_extended.log',
           report/'affine_quant_sim.log',report/'quantized-pointwise-oracle-regression.json']
    result['source_evidence_sha256']={p.relative_to(ROOT).as_posix():sha(p) for p in files}
    result['protected_artifacts_unchanged']=True
    result['physical_fpga_execution_validated']=False
    (report/'quant_firmware_evidence.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS: integrated timing, DRC, simulations, accuracy regression, bit/XSA identity and protected artifacts')


if __name__=='__main__':main()
