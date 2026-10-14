"""Create a separate reproducible physical FPGA acceleration package."""
import argparse,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark',type=Path,required=True)
    args=parser.parse_args()
    result=json.loads(args.benchmark.read_text())
    assert result['hardware_execution'] and result['runs']>=20
    assert all(c['physical_oracle_bit_parity'] for c in result['clips'])
    firmware=ROOT/'deployment/asr-v3-quant/asr-v3-quant.bit.bin'
    library=ROOT/'software/ort_fpga/libort_fpga.so'
    assert sha(firmware)==result['firmware_sha256']
    assert sha(library)==result['library_sha256']
    assert sha(ROOT/'deployment/experimental-quant/qn_tile.ko')==result['driver_sha256']
    preserved={p.name:sha(p) for p in ROOT.glob('prototype-v2-*.zip')}
    files=[]
    for directory in ('software/ort_fpga','software/fused','deployment/experimental-quant',
                      'deployment/asr-v3-quant','sim/affine_vectors',
                      'research/eval/user-recording','research/eval/user-stress-ac'):
        files.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and
                     '__pycache__' not in p.parts and p.suffix not in ('.o','.cmd'))
    files.extend(ROOT/p for p in ('research/fused/cpu-int8.onnx','research/fused/cpu-int8.json',
                 'software/model-tools/citrinet_cpu.py','software/evaluation/benchmark.py',
                 'software/requirements-runtime.txt','PLAN_V3.md','RESULTS_V3.md',
                 'rtl/experimental/qn_quant_axis.v','rtl/experimental/fused_affine_quant.v',
                 'sim/tb_qn_quant_axis.sv','sim/tb_fused_affine_quant.sv',
                 'scripts/quant_system_build.tcl','scripts/prepare_quant_firmware.py',
                 'scripts/quant_cached_sim.tcl','scripts/affine_quant_sim.tcl',
                 'scripts/generate_affine_vectors.py'))
    files.append(Path(__file__));files.extend([args.benchmark,args.benchmark.with_suffix('.onnx')])
    for pattern in ('quant_system_*.rpt','quant_*evidence.json','quant_*implementation.json',
                    '*quant*smoke*.json','quantized-pointwise-oracle-regression.json',
                    'quant_cached_sim_extended.log','affine_quant_sim.log','ort-fpga*probe.json'):
        files.extend((ROOT/'reports/fused').glob(pattern))
    files.append(ROOT/'reports/fused/quant_driver_protocol.log')
    files.append(ROOT/'reports/fused/quant_vector_transpose.log')
    files=sorted(set(p.resolve() for p in files))
    hashes={p.relative_to(ROOT).as_posix():sha(p) for p in files}
    destination=ROOT/'prototype-v3-quant-acceleration.zip'
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for relative in hashes:archive.write(ROOT/relative,relative)
        archive.writestr('QUANT_SHA256SUMS',''.join(f'{v}  {k}\n' for k,v in hashes.items()))
    with zipfile.ZipFile(destination) as archive:
        for relative,digest in hashes.items():assert hashlib.sha256(archive.read(relative)).hexdigest()==digest
    for name,digest in preserved.items():assert sha(ROOT/name)==digest
    wins=[c['id'] for c in result['clips'] if c['fpga_p50']<c['cpu_p50'] and
          c['fpga_p95']<c['cpu_p95'] and c['mean_saving_95ci_seconds'][0]>0 and
          (c['fpga_errors']-c['cpu_errors'])/c['reference_words']<=.01]
    report={'archive':destination.name,'sha256':sha(destination),'files':hashes,
            'preserved_archives':preserved,'physical_paired_winning_clips':wins,
            'representative_corpus_claimed':False,'sustained_capture_validated':False}
    (ROOT/'reports/fused/quant_package.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='files'},indent=2))
if __name__=='__main__':main()
