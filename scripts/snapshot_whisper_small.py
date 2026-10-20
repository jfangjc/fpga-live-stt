"""Save the small experiment and standalone decision with verified file hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument('--destination', type=Path, required=True)
    a = ap.parse_args()
    project, destination = a.project.resolve(), a.destination.resolve()
    if destination.exists() or destination.is_relative_to(project):
        ap.error('Destination must be new and outside the project')
    qpath = project/'reports/whisper-small/qualification.json'
    q = json.loads(qpath.read_text())
    if q['model'] != 'openai/whisper-small' or not q['prototype_gates_passed']:
        raise RuntimeError('Expected completed small-model measurement evidence')
    for name, value in q['evidence_sha256'].items():
        if digest(project/'reports/whisper-small'/name) != value:
            raise RuntimeError('Measurement evidence hash mismatch: '+name)
    bundle = project/'release/whisper-small-board-assets-20261020.zip'
    if digest(bundle) != bundle.with_suffix('.zip.sha256').read_text().split()[0]:
        raise RuntimeError('Development assets archive hash mismatch')
    verified = json.loads((project/'reports/whisper-small/development_assets_check.json').read_text())
    if not verified['all_file_hashes_and_crc_verified'] or verified['sha256'] != digest(bundle):
        raise RuntimeError('Development assets were not fully verified')
    sources = sorted(p for p in project.rglob('*') if p.is_file())
    destination.mkdir(parents=True, exist_ok=False)
    entries = {}
    for source in sources:
        if not source.resolve().is_relative_to(project):
            raise RuntimeError('Source link escapes project: '+str(source))
        relative = source.relative_to(project)
        target = destination/'Project'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        value = digest(source)
        if digest(target) != value:
            raise RuntimeError('Snapshot hash mismatch: '+str(relative))
        entries[relative.as_posix()] = {'bytes': source.stat().st_size, 'sha256': value}
    decision = project/'docs/WHISPER_SMALL_LIVE_DECISION.md'

    def relocate(match):
        link = match[1]
        if link.startswith(('https://', 'http://')):
            return match[0]
        path = (decision.parent/link).resolve()
        return '](Project/'+path.relative_to(project).as_posix()+')'

    standalone = destination/'WHY_WHISPER_SMALL_IS_NOT_VIABLE.md'
    standalone.write_text(re.sub(r'\]\(([^)]+)\)', relocate, decision.read_text(encoding='utf-8')), encoding='utf-8')
    manifest = {'model': 'openai/whisper-small', 'decision': 'Not accepted for live transcription with the current KV260 full-context implementation',
                'scope': 'Complete local project plus tested board models, runtimes and source in release/whisper-small-board-assets-20261020.zip; development backup, not a deployed streaming release',
                'qualification_sha256': digest(qpath), 'files': entries,
                'standalone_decision': {'name': standalone.name, 'sha256': digest(standalone)}}
    (destination/'SNAPSHOT_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps({'destination': str(destination), 'project_files': len(entries),
                      'project_bytes': sum(x['bytes'] for x in entries.values()), 'verified': True,
                      'decision': str(standalone)}, indent=2), flush=True)


if __name__ == '__main__':
    main()
