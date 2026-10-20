"""Package isolated v3 software experiments without replacing tested archives."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    preserved = {p.name: sha(p) for p in ROOT.glob('prototype-v2-*.zip')}
    files = list((ROOT/'software/fused').glob('*.py'))
    files.extend(p for p in (ROOT/'software/fused').glob('*.md'))
    files += [ROOT/'software/model-tools/citrinet_cpu.py', ROOT/'software/evaluation/benchmark.py',
              ROOT/'software/requirements-runtime.txt', ROOT/'PLAN_V3.md', ROOT/'RESULTS_V3.md', Path(__file__)]
    files += [p for p in (ROOT/'reports/fused').rglob('*.json') if not p.name.startswith('ort_') and p.name != 'package.json']
    files += [p for p in (ROOT/'reports/fused').rglob('selected_block*') if p.is_file()]
    files += list((ROOT/'reports/fused/board-source-snapshot').rglob('*.py'))
    files += [p for p in (ROOT/'research/fused').rglob('*') if p.is_file()]
    files += [p for p in (ROOT/'research/eval/user-recording').rglob('*') if p.is_file()]
    for folder in ('user-stress', 'user-stress-ac'):
        files += [p for p in (ROOT/'research/eval'/folder).rglob('*') if p.is_file()]
    files += [ROOT/'rtl/experimental/fused_requant.v', ROOT/'sim/tb_fused_requant.sv',
              ROOT/'scripts/generate_requant_vectors.py', ROOT/'scripts/fused_requant_sim.tcl',
              ROOT/'scripts/fused_requant_impl.tcl']
    files += [ROOT/'rtl/experimental/fused_se_reduce.v', ROOT/'sim/tb_fused_se_reduce.sv',
              ROOT/'scripts/generate_se_vectors.py', ROOT/'scripts/fused_se_sim.tcl',
              ROOT/'scripts/fused_se_impl.tcl', ROOT/'scripts/generate_user_stress.py',
              ROOT/'scripts/verify_fused_evidence.py']
    files += [p for p in (ROOT/'sim/se_vectors').glob('*') if p.is_file()]
    files += [p for p in (ROOT/'sim/fused_vectors').glob('*') if p.is_file()]
    files += [p for p in (ROOT/'reports/fused').glob('requant*') if p.is_file() and '.backup.' not in p.name]
    files += [p for p in (ROOT/'reports/fused').glob('se_*') if p.is_file()]
    hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(set(files))}
    archive_path = ROOT/'prototype-v3-fused-experiments.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for relative in hashes:
            archive.write(ROOT/relative, relative)
        archive.writestr('FUSED_SHA256SUMS', ''.join(f'{h}  {p}\n' for p, h in hashes.items()))
    with zipfile.ZipFile(archive_path) as archive:
        for relative, expected in hashes.items():
            assert hashlib.sha256(archive.read(relative)).hexdigest() == expected
    for name, expected in preserved.items():
        assert sha(ROOT/name) == expected, 'Existing deployment archive changed'
    report = {'archive': archive_path.name, 'sha256': sha(archive_path), 'files': hashes,
              'preserved_archives': preserved, 'firmware_changed': False,
              'physical_fpga_acceleration_demonstrated': False}
    (ROOT/'reports/fused/package.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    main()
