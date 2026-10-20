"""Derive a deployable subset from the verified full MVP handoff archive."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT/'release/kv260-asr-mvp-1.0.1.zip'
    target = ROOT/'release/kv260-asr-mvp-1.0.1-runtime.zip'
    with zipfile.ZipFile(source) as original:
        manifest = json.loads(original.read('release/MVP_MANIFEST.json'))
        selected = set()
        for name in manifest['files_sha256']:
            if name.startswith(('software/', 'scripts/', 'rtl/', 'hardware/', 'verification/', 'docs/')) or name == 'README.md':
                selected.add(name)
            elif name.startswith('reports/fused/') and name.endswith('.json'):
                selected.add(name)
            elif name.startswith('reports/mvp/') and (Path(name).name.startswith(('clean_', 'bulk_before_', 'bulk_restored_'))):
                selected.add(name)
            elif name.startswith('research/export/citrinet-256-ls/') or name in ('research/fused/cpu-int8-cse.onnx', 'research/fused/cpu-int8-cse.json'):
                selected.add(name)
            elif name.startswith(('deployment/asr-v3-bulk/', 'deployment/asr-v3-branch512-ab166/')) and name.endswith(('.bit.bin', '.dtbo', 'shell.json')):
                selected.add(name)
            elif name.startswith(('deployment/kernel-compat/', 'deployment/experimental-stream-branch/')):
                selected.add(name)
        # Live artifact loading checks the entire NEON proof, including its log.
        visited = set()
        def include_proof(name):
            if name in visited:
                return
            visited.add(name)
            selected.add(name)
            if name.endswith('.json'):
                data = json.loads(original.read(name))
                for key in ('sources_sha256', 'sources_and_evidence_sha256'):
                    for child in data.get(key, {}):
                        include_proof(child)
        include_proof('reports/fused/branch512_neon_evidence.json')
        runtime = manifest | {'deployment_bundle': True,
            'source_handoff_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'files_sha256': {name: manifest['files_sha256'][name] for name in sorted(selected)}}
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
            for name in sorted(selected):
                data = original.read(name)
                if hashlib.sha256(data).hexdigest() != runtime['files_sha256'][name]:
                    raise ValueError('Handoff file hash mismatch: '+name)
                output.writestr(name, data)
            output.writestr('release/MVP_MANIFEST.json', json.dumps(runtime, indent=2)+'\n')
    with zipfile.ZipFile(target) as archive:
        for name, expected in runtime['files_sha256'].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError('Deployment archive hash mismatch: '+name)
    (ROOT/'release/RUNTIME_SHA256SUMS.txt').write_text(hashlib.sha256(target.read_bytes()).hexdigest()+'  '+target.name+'\n')
    print('PASS: runtime bundle', len(selected), 'files;', target.stat().st_size, 'bytes')


if __name__ == '__main__':
    main()
