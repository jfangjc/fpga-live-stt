"""Back up tested small models, runtimes and sources; not a runtime release."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work', type=Path, required=True)
    ap.add_argument('--original', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    if a.out.exists():
        ap.error('Refusing to overwrite a backup')
    qualification = json.loads((a.work/'qualification.json').read_text())
    if qualification['model'] != 'openai/whisper-small' or not qualification['prototype_gates_passed']:
        raise RuntimeError('Expected completed small-model evidence')
    files = {}

    def add(path, name):
        if not path.is_file() or name in files:
            raise RuntimeError('Missing or duplicate asset: '+str(path))
        files[name] = path

    for model in (a.work/'models').glob('*.bin'):
        add(model, 'models/'+model.name)
    for variant in ('cpu', 'hybrid'):
        base = a.work/f'build-{variant}'
        add(base/'bin/whisper-cli', f'build-{variant}/bin/whisper-cli')
        if variant == 'cpu':
            add(base/'bin/whisper-quantize', 'build-cpu/bin/whisper-quantize')
        for directory in ('src', 'ggml/src', 'ggml/src/ggml-cpu'):
            for path in (base/directory).glob('*.so*'):
                add(path, f'build-{variant}/{directory}/{path.name}')
    add(a.work/'libqnc_parallel.so', 'libqnc_parallel.so')
    for label, source in (('upstream-cpu', a.original/'upstream'),
                          ('upstream-hybrid', a.work/'upstream-kv260'),
                          ('build_metadata', a.work/'build_metadata')):
        for path in source.rglob('*'):
            if path.is_file():
                if not path.resolve().is_relative_to(source.resolve()):
                    raise RuntimeError('Source link escapes source tree: '+str(path))
                add(path, label+'/'+path.relative_to(source).as_posix())
    for name in ('model_manifest.json', 'qualification.json', 'board_check.json'):
        add(a.work/name, name)
    entries = {}
    with zipfile.ZipFile(a.out, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, path in sorted(files.items()):
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            mode = 0o100755 if path.stat().st_mode & 0o111 else 0o100644
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_STORED if name.startswith('models/') else zipfile.ZIP_DEFLATED
            digest = hashlib.sha256()
            size = 0
            with path.open('rb') as source, archive.open(info, 'w', force_zip64=True) as target:
                while data := source.read(4*1024*1024):
                    digest.update(data)
                    size += len(data)
                    target.write(data)
            entries[name] = {'bytes': size, 'sha256': digest.hexdigest()}
        manifest = {'model': 'openai/whisper-small',
                    'purpose': 'Development asset backup; no relocated deployment or live-streaming qualification',
                    'files': entries}
        archive.writestr('DEVELOPMENT_ASSETS_MANIFEST.json', json.dumps(manifest, indent=2)+'\n')
    with a.out.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    a.out.with_suffix('.zip.sha256').write_text(digest+'  '+a.out.name+'\n')
    print(json.dumps({'archive': str(a.out), 'files': len(entries), 'bytes': a.out.stat().st_size,
                      'sha256': digest}, indent=2), flush=True)


if __name__ == '__main__':
    main()
