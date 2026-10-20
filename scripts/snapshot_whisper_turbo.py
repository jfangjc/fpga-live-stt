"""Copy and hash-verify the complete qualified turbo project."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    project, destination = args.project.resolve(), args.destination.resolve()
    if destination.exists() or destination.is_relative_to(project):
        parser.error('Destination must be new and outside the project')
    qualification = project/'reports/whisper-turbo/qualification.json'
    if not json.loads(qualification.read_text())['prototype_gates_passed']:
        raise RuntimeError('Turbo prototype has not passed its qualification gates')
    if not json.loads((project/'reports/whisper-turbo/runtime_check.json').read_text())['passed']:
        raise RuntimeError('Relocated turbo deployment has not passed')
    runtime = project/'release/kv260-whisper-large-v3-turbo-prototype-0.2.0-runtime.zip'
    expected = runtime.with_suffix('.zip.sha256').read_text().split()[0]
    if digest(runtime) != expected:
        raise RuntimeError('Runtime package checksum mismatch')
    sources = sorted(p for p in project.rglob('*') if p.is_file())
    destination.mkdir(parents=True, exist_ok=False)
    files = {}
    for source in sources:
        if not source.resolve().is_relative_to(project):
            raise RuntimeError('Source link escapes the project: '+str(source))
        relative = source.relative_to(project)
        target = destination/'Project'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        checksum = digest(source)
        if digest(target) != checksum:
            raise RuntimeError('Snapshot verification failed: '+str(relative))
        files[relative.as_posix()] = {'bytes':source.stat().st_size, 'sha256':checksum}
    manifest = {'model':'openai/whisper-large-v3-turbo', 'scope':'Complete project: all regular files, including generated builds, historical releases and new qualified runtime',
                'source':str(project), 'qualification_sha256':digest(qualification), 'files':files}
    (destination/'SNAPSHOT_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps({'destination':str(destination), 'files':len(files),
                      'bytes':sum(row['bytes'] for row in files.values()), 'verified':True}, indent=2))


if __name__ == '__main__':
    main()
