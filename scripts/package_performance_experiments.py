"""Separate source update; never overwrite the physically tested deployment ZIP."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    original=ROOT/'prototype-v2-package.zip'
    baseline=sha(original)
    expected_baseline=json.loads((ROOT/'reports/package.json').read_text())['zip_sha256']
    if baseline!=expected_baseline:
        raise RuntimeError('Original deployment ZIP differs from the recorded tested package')
    native_report=ROOT/'software/native/performance_validation.json'
    native=json.loads(native_report.read_text())
    if native.get('status')!='local_verification_passed':
        raise RuntimeError('Native local verification must pass before packaging')
    for name,expected in native['source_sha256'].items():
        if sha(ROOT/'software/native'/name)!=expected:
            raise RuntimeError('Native verification is stale: '+name)
    for test in native['executed_tests'].values():
        if test['status']!='passed' or sha(ROOT/test['path'].replace('\\','/'))!=test['sha256']:
            raise RuntimeError('Native test evidence is stale: '+test['path'])
    paths=[p for p in (ROOT/'software/native').glob('*') if p.is_file() and p.suffix in ('.c','.h','.py','.md','.sh')]
    paths.append(ROOT/'software/native/Makefile')
    paths.extend(ROOT/n for n in [
        'RESULTS.md',
        'software/runtime/profile_cpu_regions.py',
        'deployment/PERFORMANCE_EXPERIMENTS.md',
        'research/PERFORMANCE_NEXT_STAGE.md',
        'verification/BOARD_PROFILE_FINDINGS.md',
        'verification/board_profile_analysis.py',
        'verification/board_profile_analysis.json',
        'verification/audit_native_neon.py',
        'verification/native_neon_audit.json'])
    paths.extend((ROOT/'reports').glob('cpu_regions_*_local.json'))
    paths.extend(p for p in (ROOT/'reports/board_received/2026-10-09_reference').glob('*') if p.is_file())
    paths.append(native_report)
    paths.extend((ROOT/'software/native/prebuilt/aarch64').glob('*validation.txt'))
    paths.append(ROOT/'software/native/prebuilt/aarch64/provenance.json')
    paths.append(ROOT/'software/native/prebuilt/aarch64/qnc_disassembly.txt')
    paths=sorted(set(paths))
    hashes={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    checksums=''.join(f'{digest}  {relative}\n' for relative,digest in hashes.items())
    update=ROOT/'prototype-v2-performance-experiments.zip'
    with zipfile.ZipFile(update,'w',zipfile.ZIP_DEFLATED) as archive:
        for p in paths: archive.write(p,p.relative_to(ROOT).as_posix())
        archive.writestr('PERFORMANCE_SHA256SUMS',checksums)
    with zipfile.ZipFile(update) as archive:
        assert len(archive.namelist())==len(hashes)+1
        for relative,expected in hashes.items():
            assert hashlib.sha256(archive.read(relative)).hexdigest()==expected
    assert sha(original)==baseline,'Original deployment ZIP changed'
    report={'update_sha256':sha(update),'baseline_zip_sha256':baseline,
            'verified_files':len(hashes),'contents':'source-only experiments; existing firmware unchanged',
            'physical_speedup_demonstrated':False,'physical_parity_requires_rerun':True}
    (ROOT/'reports/performance_update_package.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
