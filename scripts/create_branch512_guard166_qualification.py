"""Reuse staged parity/latency gates for the isolated exact header simplification."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
paths=[p for p in (ROOT/'scripts').glob('*branch512_drop166*') if p.name.startswith(('prepare_','finalize_','install_','run_','qualify_'))]
paths+=list((ROOT/'software/latency').glob('*branch512_drop166*.py'))
paths+=list((ROOT/'software/latency').glob('test_drop_*.py'))
for path in paths:
    text=path.read_text().replace('branch512_drop166','branch512_guard166').replace('branch512-drop166','branch512-guard166')
    text=text.replace('check_branch512_drop_software.py','check_branch512_guard_software.py').replace('branch512_drop_regression_evidence.json','branch512_guard_regression_evidence.json')
    # Keep the actual historical license failure, rather than inventing a new one.
    text=text.replace('branch512_guard166_incremental_license_failure.json','branch512_drop166_incremental_license_failure.json')
    text=text.replace('test_drop_','test_guard_')
    text=text.replace('FPGA-ASR-DW-pipeline-','FPGA-ASR-header-guard-')
    if path.name.startswith('prepare_'):
        old="paths=[reference_proof]+[ROOT/path for path in reference_record['sources_sha256']]"
        extra="""
drop_parent=ROOT/'reports/fused/branch512_drop_regression_evidence.json'
drop_record=json.loads(drop_parent.read_text());assert drop_record['complete']
for path,value in drop_record['sources_sha256'].items():assert sha(ROOT/path)==value,path
paths += [drop_parent]+[ROOT/path for path in drop_record['sources_sha256']]
"""
        assert old in text;text=text.replace(old,old+extra)
    name=path.relative_to(ROOT).as_posix().replace('branch512_drop166','branch512_guard166').replace('test_drop_','test_guard_')
    dest=ROOT/name
    if dest.exists():assert dest.read_text()==text,dest
    else:dest.write_text(text,newline='\n')
stage=(ROOT/'scripts/verify_branch512_drop166_stage.py').read_text().replace('branch512_drop166','branch512_guard166').replace('test_drop_','test_guard_')
dest=ROOT/'scripts/verify_branch512_guard166_stage.py'
if dest.exists():assert dest.read_text()==stage
else:dest.write_text(stage,newline='\n')
print('Prepared isolated guard166 firmware and sequential physical parity/latency tools')
