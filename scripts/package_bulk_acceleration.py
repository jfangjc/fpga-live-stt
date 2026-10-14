"""Create a separate reproducible physical FPGA acceleration package."""
import argparse,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark',type=Path,required=True)
    parser.add_argument('--regression',type=Path,required=True)
    args=parser.parse_args()
    result=json.loads(args.benchmark.read_text())
    assert result['hardware_execution'] and result['runs']>=50 and result['complete']
    assert all(c['fpga_p50']<c['cpu_p50'] and c['fpga_p95']<c['cpu_p95'] and
               c['mean_saving_95ci_seconds'][0]>0 and
               (c['fpga_errors']-c['cpu_errors'])/c['reference_words']<=.01
               for c in result['clips']), 'Physical paired latency/accuracy acceptance failed'
    assert all(c['physical_oracle_bit_parity'] for c in result['clips'])
    regression=json.loads(args.regression.read_text())
    assert regression['complete'] and regression['hardware_execution'] and regression['runs']>=50
    assert len(regression['clips'])>=9
    assert all(c['physical_oracle_bit_parity'] for c in regression['clips'])
    assert sum(c['fpga_errors']-c['cpu_errors'] for c in regression['clips'])/sum(c['reference_words'] for c in regression['clips'])<=.01
    for key in ('nodes','model_sha256','library_sha256','firmware_sha256','driver_sha256'):
        assert regression[key]==result[key], key
    for name,digest in regression['sources_sha256'].items():
        assert sha(ROOT/'software/ort_fpga_bulk/accepted_sources'/name)==digest, name
    evidence=json.loads((ROOT/'reports/fused/bulk_physical_firmware_evidence.json').read_text())
    assert evidence['physical_fpga_execution_validated'] and evidence['end_to_end_cpu_speedup_validated']
    for relative,digest in evidence['source_evidence_sha256'].items():assert sha(ROOT/relative)==digest,relative
    assert evidence['end_to_end_report_sha256']==sha(args.benchmark)
    assert evidence['corpus_report_sha256']==sha(args.regression)
    firmware=ROOT/'deployment/asr-v3-bulk/asr-v3-bulk.bit.bin'
    library=ROOT/'software/ort_fpga_bulk/libort_fpga.so'
    assert sha(firmware)==result['firmware_sha256']
    assert sha(library)==result['library_sha256']
    assert sha(ROOT/'deployment/experimental-bulk/qn_tile.ko')==result['driver_sha256']
    preserved={p.name:sha(p) for p in ROOT.glob('prototype-v2-*.zip')}
    files=[]
    for directory in ('software/ort_fpga_bulk','software/fused','deployment/experimental-bulk',
                      'deployment/asr-v3-bulk','sim/affine_vectors',
                      'research/eval/user-recording','research/eval/user-stress-ac','research/eval/original-reference','research/eval/librispeech-mini',
                      'research/export/citrinet-256-ls'):
        files.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and
                     '__pycache__' not in p.parts and p.suffix not in ('.o','.cmd'))
    files.extend(ROOT/p for p in ('research/fused/cpu-int8.onnx','research/fused/cpu-int8.json',
                 'software/model-tools/citrinet_cpu.py','software/evaluation/benchmark.py',
                 'software/requirements-runtime.txt','PLAN_V3.md','RESULTS_V3.md',
                 'rtl/experimental/qn_bulk_axis.v','rtl/experimental/fused_affine_quant.v',
                 'sim/tb_qn_bulk_axis.sv','sim/tb_fused_affine_quant.sv',
                 'scripts/bulk_system_build.tcl','scripts/prepare_bulk_firmware.py',
                 'scripts/bulk_cached_sim.tcl','scripts/affine_quant_sim.tcl',
                 'scripts/generate_affine_vectors.py','sim/tb_qn_bulk_errors.sv',
                 'scripts/bulk_errors_sim.tcl','scripts/vivado_four_threads.tcl',
                 'scripts/report_bulk_results.py','reports/fused/bulk_acceptance_summary.md',
                 'reports/fused/board-int8-1-paired.json','reports/fused/board-int8-2-paired.json',
                 'reports/fused/board-int8-4-paired.json','reports/fused/board-user-int8-4-paired.json'))
    files.append(Path(__file__));files.extend([args.benchmark,args.benchmark.with_suffix('.onnx'),args.regression,args.regression.with_suffix('.onnx')])
    for pattern in ('bulk_system_*.rpt','bulk_*evidence.json','bulk_*implementation.json',
                    '*bulk*smoke*.json','bulk_oracle_regression.json',
                    'bulk_cached_sim_watchdog.log','affine_quant_sim.log','bulk_errors_sim.log','bulk_pointwise_screen.json','bulk_three_original_reference.json','bulk_three_original_reference.onnx','bulk_runtime_cli.jsonl'):
        files.extend((ROOT/'reports/fused').glob(pattern))
    files.append(ROOT/'reports/fused/bulk_driver_protocol.log')
    files.append(ROOT/'reports/fused/quant_vector_transpose.log')
    files=sorted(set(p.resolve() for p in files))
    hashes={p.relative_to(ROOT).as_posix():sha(p) for p in files}
    destination=ROOT/'prototype-v3-bulk-acceleration.zip'
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for relative in hashes:archive.write(ROOT/relative,relative)
        archive.writestr('BULK_SHA256SUMS',''.join(f'{v}  {k}\n' for k,v in hashes.items()))
    with zipfile.ZipFile(destination) as archive:
        for relative,digest in hashes.items():assert hashlib.sha256(archive.read(relative)).hexdigest()==digest
    for name,digest in preserved.items():assert sha(ROOT/name)==digest
    wins=[c['id'] for c in result['clips'] if c['fpga_p50']<c['cpu_p50'] and
          c['fpga_p95']<c['cpu_p95'] and c['mean_saving_95ci_seconds'][0]>0 and
          (c['fpga_errors']-c['cpu_errors'])/c['reference_words']<=.01]
    report={'archive':destination.name,'sha256':sha(destination),'files':hashes,
            'preserved_archives':preserved,'physical_paired_winning_clips':wins,
            'regression_clips':regression['clips'],'regression_complete':True,
            'representative_corpus_claimed':False,'sustained_capture_validated':False}
    (ROOT/'reports/fused/bulk_package.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='files'},indent=2))
if __name__=='__main__':main()
