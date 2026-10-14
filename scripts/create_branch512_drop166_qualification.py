"""Preserve OUTSLICE tools; bind the new exact DW stage to separate firmware."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
names=[
 'scripts/prepare_branch512_outslice166_firmware.py','scripts/finalize_branch512_outslice166_firmware.py',
 'scripts/install_branch512_outslice166_firmware.py','scripts/run_branch512_outslice166_board.sh',
 'scripts/qualify_branch512_outslice166.py','software/latency/branch512_outslice166_benchmark.py',
 'software/latency/test_branch512_outslice166_blocks.py','software/latency/validate_branch512_outslice166_physical.py',
 'software/latency/tune_branch512_outslice166_policy.py','software/latency/confirm_branch512_outslice166_latency.py']
for variant in ('scale','more','neon','maskfast'):
    names += [f'scripts/qualify_branch512_outslice166_{variant}.py',
              f'software/latency/branch512_outslice166_{variant}_benchmark.py',
              f'software/latency/validate_branch512_outslice166_{variant}_physical.py',
              f'software/latency/tune_branch512_outslice166_{variant}_policy.py',
              f'software/latency/confirm_branch512_outslice166_{variant}_latency.py']
for old,new in (('test_outslice_scale_split_pairs_physical.py','test_drop_scale_split_pairs_physical.py'),('test_outslice_stride_pointwise_physical.py','test_drop_stride_pointwise_physical.py'),('test_outslice_neon_pointwise_physical.py','test_drop_neon_pointwise_physical.py')):
    text=(ROOT/'software/latency'/old).read_text().replace('branch512_outslice166','branch512_drop166')
    dest=ROOT/'software/latency'/new
    if dest.exists():assert dest.read_text()==text,dest
    else:dest.write_text(text,newline='\n')
for name in names:
    text=(ROOT/name).read_text().replace('branch512_outslice166','branch512_drop166').replace('branch512-outslice166','branch512-drop166')
    text=text.replace('check_branch512_outslice_software.py','check_branch512_drop_software.py').replace('branch512_outslice_regression_evidence.json','branch512_drop_regression_evidence.json')
    if name.startswith('scripts/prepare_'):
        text=text.replace('paths=[]', '''reference_proof=ROOT/'reports/fused/branch512_drop166_incremental_license_failure.json'
reference_record=json.loads(reference_proof.read_text());assert reference_record['complete']
assert not reference_record['incremental_license_supported']
for path,value in reference_record['sources_sha256'].items():assert sha(ROOT/path)==value,path
paths=[reference_proof]+[ROOT/path for path in reference_record['sources_sha256']]''')
        text=text.replace('timing.update(complete=True,', "timing.update(incremental_implementation=False,implementation_flow='full',complete=True,")
    for old,new in (('test_outslice_scale_split_pairs_physical.py','test_drop_scale_split_pairs_physical.py'),('test_outslice_stride_pointwise_physical.py','test_drop_stride_pointwise_physical.py'),('test_outslice_neon_pointwise_physical.py','test_drop_neon_pointwise_physical.py')):
        text=text.replace(old,new)
    text=text.replace('FPGA-ASR-output-pipeline-retention-confirmed-2026-10-13','FPGA-ASR-DW-pipeline-retention-confirmed-2026-10-13').replace('FPGA-ASR-output-pipeline-vector-confirmed-2026-10-13','FPGA-ASR-DW-pipeline-vector-confirmed-2026-10-13').replace('FPGA-ASR-output-pipeline-maskfast-confirmed-2026-10-13','FPGA-ASR-DW-pipeline-maskfast-confirmed-2026-10-13')
    dest=ROOT/name.replace('branch512_outslice166','branch512_drop166')
    if dest.exists():assert dest.read_text()==text,dest
    else:dest.write_text(text,newline='\n')
print('Prepared separate DW-pipeline deployment and sequential physical parity/latency tools')
