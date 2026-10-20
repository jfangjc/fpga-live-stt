"""Check a relocated runtime, successful inference and failed-command restoration.

Run as root on the prepared KV260 after extracting a new runtime directory.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.out.exists():
        parser.error('Refusing to overwrite evidence')
    harness = root/'software/whisper'
    subprocess.run([sys.executable, str(harness/'verify_runtime.py'), '--root', str(root), '--libraries'], check=True)
    manifest = root/'research/whisper-validation/evaluation.jsonl'
    sample = json.loads(manifest.read_text().splitlines()[0])
    audio = manifest.parent/sample['audio']
    package = json.loads((root/'WHISPER_MANIFEST.json').read_text())
    reporting = 'whisper-turbo' if package['model']=='openai/whisper-large-v3-turbo' else 'whisper'
    report = json.loads((root/f'reports/{reporting}/validation_results/results.json').read_text())
    reference = next(row for row in report['clips'] if Path(row['audio']).name==audio.name)['rows']['hybrid'][0]['text']
    output = root/'reports/deployment-check'
    output.mkdir(exist_ok=False)
    result = {'root':str(root), 'manifest_and_relocated_libraries':True, 'runs':{}}
    for language in ('en', 'auto'):
        transcript = output/f'{language}.json'
        subprocess.run([sys.executable, str(harness/'run_board.py'), str(audio), '--work', str(root),
                        '--release', str(root), '--language', language, '--out', str(transcript)], check=True)
        row = json.loads(transcript.read_text())
        session = json.loads(transcript.with_suffix('.session.json').read_text())
        if row['text']!=reference or not session['restored']:
            raise RuntimeError('Relocated transcript or restoration mismatch')
        result['runs'][language] = {'seconds':row['seconds'], 'exact_qualified_transcript':True,
                                     'physical_counters':row['physical_counters'], 'restored':True}
    failure = output/'expected-failure.session.json'
    status = subprocess.run([sys.executable, str(harness/'hardware_session.py'), '--release', str(root),
                             '--expected-app', 'k26-starter-kits', '--evidence', str(failure), '--',
                             sys.executable, '-c', 'raise SystemExit(7)']).returncode
    session = json.loads(failure.read_text())
    if status!=7 or not session['restored']:
        raise RuntimeError('Failed-command status/restoration check failed')
    result['expected_failure'] = {'exit_code':status, 'restored':True}
    result['passed'] = True
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
