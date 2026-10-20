"""Verify a relocated Whisper runtime against its complete SHA256 manifest."""
import argparse
import hashlib
import json
from pathlib import Path
from benchmark import check_model,dependencies


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
    ap.add_argument('--libraries',action='store_true',help='Also check Linux shared-library resolution')
    a = ap.parse_args()
    root = a.root.resolve()
    manifest = json.loads((root/'WHISPER_MANIFEST.json').read_text())
    for name,entry in manifest['files'].items():
        path = (root/name).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Manifest path escapes runtime root')
        if path.stat().st_size!=entry['bytes']:
            raise ValueError('Size mismatch: '+name)
        with path.open('rb') as f:
            digest = hashlib.file_digest(f,'sha256').hexdigest()
        if digest != entry['sha256']:
            raise ValueError('SHA256 mismatch: '+name)
    short = manifest['model'].removeprefix('openai/whisper-')
    if check_model(root/f'ggml-{short}-q8_0.bin')!=manifest['model']:
        raise ValueError('Manifest/model architecture mismatch')
    if a.libraries:
        for variant in ('cpu','hybrid'):
            libraries = dependencies(root/f'build-{variant}/bin/whisper-cli')
            local = [Path(p) for p in libraries if Path(p).name.startswith(('libwhisper','libggml'))]
            if len(local)<4 or any(not p.resolve().is_relative_to(root) for p in local):
                raise ValueError('Shared libraries resolved outside this runtime: '+str(local))
    print(f'PASS: {len(manifest["files"])} files, {manifest["model"]}, and requested library checks')


if __name__ == '__main__':
    main()
