"""Package the verified MVP and its evidence without environments or build caches."""
import json
from pathlib import Path
import zipfile
from verify_mvp import ROOT, audit, digest, verify_manifest


def main():
    audit()
    files = set()
    extensions = {'.py', '.c', '.cc', '.cpp', '.h', '.v', '.sv', '.vh', '.svh',
                  '.tcl', '.sh', '.ps1', '.bat', '.xdc', '.json', '.jsonl', '.yaml',
                  '.yml', '.md', '.txt', '.mem', '.so', '.ko', '.bif', '.dts', '.dtbo',
                  '.npz', '.onnx', '.rpt', '.log', '.bd', '.xci', '.xpr', '.xml'}
    excluded = {'__pycache__', '.git', 'node_modules', 'site-packages', 'linux-tools', 'uv-cache'}
    # Include existing runtime dependencies and historical checks invoked by gates.
    for folder in ('software', 'scripts', 'rtl', 'hardware', 'sim', 'verification', 'docs'):
        for path in (ROOT / folder).rglob('*'):
            relative = path.relative_to(ROOT)
            if any(p in excluded or p.startswith('.venv') for p in relative.parts):
                continue
            if path.is_file() and (path.suffix in extensions or path.name in ('Makefile', 'Kbuild', 'LICENSE')):
                files.add(relative.as_posix())
    for folder in ('reports/fused', 'reports/mvp', 'research/export/citrinet-256-ls'):
        for path in (ROOT / folder).glob('*'):
            if path.is_file() and path.suffix in extensions:
                if folder == 'reports/fused' and path.suffix == '.onnx' and path.name != 'branch512_ab166_vf_physical_validation.onnx':
                    continue
                files.add(path.relative_to(ROOT).as_posix())
    for path in (ROOT/'research/eval').rglob('*.jsonl'):
        files.add(path.relative_to(ROOT).as_posix())
    for name in ('research/fused/cpu-int8-cse.onnx', 'research/fused/cpu-int8-cse.json', 'README.md',
                 'build/generated/asr_v2_top.v'):
        files.add(name)
    # Keep recordings outside the release: operators supply their own WAVs.
    # Benchmark reproduction additionally needs the original evaluation recordings.
    for folder in ('deployment/asr-v3-branch512-ab166', 'deployment/asr-v3-bulk',
                   'deployment/kernel-compat', 'deployment/experimental-stream-branch'):
        for path in (ROOT / folder).rglob('*'):
            if path.is_file():
                files.add(path.relative_to(ROOT).as_posix())
    for folder in ('branch512_ab166_system', 'branch512_guard166_system'):
        base = ROOT / 'build' / folder
        for path in base.rglob('*'):
            if path.is_file() and (path.suffix == '.xpr' or
                    ('.srcs' in str(path) and path.suffix in extensions)):
                files.add(path.relative_to(ROOT).as_posix())
    # Include the transitive files whose exact bytes make up firmware evidence.
    def add_bound(name):
        if name in files and not name.endswith('.json'):
            return
        files.add(name)
        if name.endswith('.json'):
            data = json.loads((ROOT / name).read_text())
            for key in ('sources_sha256', 'sources_and_evidence_sha256'):
                for child in data.get(key, {}):
                    if child not in bound_seen:
                        bound_seen.add(child)
                        add_bound(child)
    bound_seen = set()
    add_bound('reports/fused/branch512_ab166_firmware_evidence.json')
    # Chained checks include earlier exact arithmetic and protocol evidence.
    for report in (ROOT / 'reports/fused').glob('*evidence.json'):
        data = json.loads(report.read_text())
        for key in ('sources_sha256', 'sources_and_evidence_sha256'):
            for name in data.get(key, {}):
                if (ROOT/name).is_file() and (ROOT/name).suffix not in {'.bit', '.bin', '.xsa', '.dtbo', '.onnx', '.wav'}:
                    files.add(name)
    for name in json.loads((ROOT/'reports/mvp/verification.json').read_text())['fresh_simulations_sha256']:
        files.add(name)
    release = ROOT / 'release'
    release.mkdir(exist_ok=True)
    manifest = {'release': 'kv260-asr-mvp-1.0.1', 'date': '2026-10-15',
                'scope': '16 kHz mono WAV, 0.02 <= duration < 2.56 s, KV260 ARM64',
                'capture_qualified': False, 'representative_wer_qualified': False,
                'recordings_included': False,
                'files_sha256': {name: digest(ROOT/name) for name in sorted(files)}}
    target = release / 'MVP_MANIFEST.json'
    target.write_text(json.dumps(manifest, indent=2) + '\n')
    verify_manifest(target)
    archive = release / 'kv260-asr-mvp-1.0.1.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for name in sorted(files):
            bundle.write(ROOT/name, name)
        bundle.write(target, 'release/MVP_MANIFEST.json')
    with zipfile.ZipFile(archive) as bundle:
        if any(name.lower().endswith('.wav') for name in bundle.namelist()):
            raise ValueError('Evaluation recording unexpectedly included in release')
        for name, expected in manifest['files_sha256'].items():
            import hashlib
            if hashlib.sha256(bundle.read(name)).hexdigest() != expected:
                raise ValueError('Archive verification failed: ' + name)
    (release/'SHA256SUMS.txt').write_text(digest(archive)+'  '+archive.name+'\n')
    print('PASS: verified release:', archive, 'files:', len(files), 'bytes:', archive.stat().st_size)


if __name__ == '__main__':
    main()
