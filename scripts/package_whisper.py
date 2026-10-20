"""Package the physically tested KV260 Whisper runtime and its source/evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import zipfile


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work',required=True,type=Path)
    ap.add_argument('--project',required=True,type=Path)
    ap.add_argument('--release',required=True,type=Path)
    ap.add_argument('--out',required=True,type=Path)
    a = ap.parse_args()
    if a.out.exists():
        ap.error('Refusing to overwrite an archive')
    qualification = json.loads((a.work/'qualification.json').read_text())
    if not qualification['prototype_gates_passed']:
        raise RuntimeError('Cannot package before the prototype gates pass')
    identity = qualification.get('model','openai/whisper-base')
    short = identity.removeprefix('openai/whisper-')
    if short not in ('base', 'large-v3-turbo'):
        raise ValueError('This packager supports the preserved base/turbo releases only; small currently has measurement evidence, not a runtime release')
    reporting = 'whisper-turbo' if short=='large-v3-turbo' else 'whisper'
    results_doc = 'WHISPER_TURBO_RESULTS.md' if short=='large-v3-turbo' else 'WHISPER_RESULTS.md'
    files = {}
    files['README.md'] = b'''# KV260 Whisper base prototype

Read docs/WHISPER_RESULTS.md for measured latency, accuracy and limits, and
docs/WHISPER_MIGRATION.md for architecture, dependencies and rebuilding.
This runtime targets the prepared KV260 running kernel 6.8.0-1036-xilinx.
Start from the k26-starter-kits application with no qn_tile module loaded.

From this extracted directory, verify and transcribe a 16 kHz mono PCM WAV:

```sh
python3 software/whisper/verify_runtime.py --libraries
sudo python3 software/whisper/run_board.py /absolute/path/clip.wav \\
  --work "$PWD" --release "$PWD" --language en --out reports/transcript.json
```

The runner checks firmware and driver compatibility, activates the FPGA, runs
inference and restores the starter application. Each output path must be new.
Use --language auto for automatic detection; benchmark qualification uses English.
Application activation/restoration is separate from the reported processing gate.
The packaged sources fetch the exact pinned upstream when rebuilt. The complete
saved Vivado project additionally preserves RTL, build projects and old releases.
'''
    files['README.md'] = files['README.md'].replace(b'Whisper base',('Whisper '+short).encode()).replace(
        b'WHISPER_RESULTS.md',results_doc.encode())
    def add(path,name):
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        if name in files:
            raise ValueError('Duplicate archive entry: '+name)
        files[name] = path
    for path in (a.project/'software/whisper').iterdir():
        if path.is_file() and path.suffix in ('.py','.h','.inc','.sh'):
            add(path,'software/whisper/'+path.name)
    for name in ('qnc_transport.c','qnc.h'):
        add(a.project/'software/ort_fpga_bulk'/name,'software/ort_fpga_bulk/'+name)
    for name in ('package_whisper.py','whisper_board.py','summarize_whisper.py','verify_whisper_deployment.py'):
        add(a.project/'scripts'/name,'scripts/'+name)
    documents = ['WHISPER_MIGRATION.md',results_doc]
    if short=='large-v3-turbo':
        documents.append('WHISPER_TURBO.md')
        files['README.md'] = files['README.md'].replace(b'docs/WHISPER_MIGRATION.md',b'docs/WHISPER_TURBO.md')
    for name in documents:
        add(a.project/'docs'/name,'docs/'+name)
    for variant in ('cpu','hybrid'):
        base = a.work/f'build-{variant}'
        add(base/'bin/whisper-cli',f'build-{variant}/bin/whisper-cli')
        for directory in ('src','ggml/src','ggml/src/ggml-cpu'):
            for path in (base/directory).glob('*.so*'):
                add(path,f'build-{variant}/{directory}/{path.name}')
    provenance_path = a.work/'model_manifest.json'
    if provenance_path.exists():
        provenance = json.loads(provenance_path.read_text())
        if provenance['model']!=identity:
            raise ValueError('Model provenance and qualification differ')
        source = next(path for path in provenance['models'] if path.endswith('-q8_0.bin'))
        add(a.work/source,f'ggml-{short}-q8_0.bin')
        add(provenance_path,f'reports/{reporting}/model_manifest.json')
    else:
        if short!='base':
            raise ValueError('Turbo requires model provenance')
        add(a.work/'model-base-q8_0.bin','ggml-base-q8_0.bin')
    for name in ('LICENSE','ggml/LICENSE'):
        path = a.work/'upstream'/name
        if path.exists():
            add(path,'licenses/'+name.replace('/','-'))
    add(a.project/'software/whisper/WHISPER_MODEL_LICENSE.txt','licenses/OPENAI-WHISPER-MIT.txt')
    for name in ('asr-v3-bulk.bit.bin','asr-v3-bulk.dtbo','shell.json'):
        add(a.release/'deployment/asr-v3-bulk'/name,'deployment/asr-v3-bulk/'+name)
    kernel = platform.release()
    relative = f'deployment/kernel-compat/{kernel}/bulk/qn_tile.ko'
    add(a.release/relative,relative)
    for path in (a.project/'deployment/experimental-bulk').iterdir():
        if path.is_file() and (path.suffix in ('.c','.h') or path.name=='Makefile'):
            add(path,'deployment/experimental-bulk/'+path.name)
    for folder in ('validation_results','latency_results'):
        for path in (a.work/folder).iterdir():
            if path.is_file():
                add(path,f'reports/{reporting}/{folder}/{path.name}')
    for name in ('parallel_conformance.json','parallel_session.json','validation_session.json',
                 'latency_session.json','validation_wer.json','latency_wer.json','qualification.json'):
        add(a.work/name,f'reports/{reporting}/'+name)
    if short=='large-v3-turbo':
        for name in ('attention_screen.json','attention_screen.log','cpu-q8-smoke.json','cpu-q8-smoke.log',
                     'cpu-q8-smoke.time.txt','hybrid-parallel-weight.json','hybrid-parallel-weight.log',
                     'hybrid-parallel-weight.time.txt','parallel_weight_session.json',
                     'auto-smoke.json','auto-smoke.log','auto_smoke_session.json'):
            add(a.work/name,f'reports/{reporting}/development/'+name)
    for path in (a.work/'validation-ten').rglob('*'):
        if path.is_file():
            add(path,'research/whisper-validation/'+path.relative_to(a.work/'validation-ten').as_posix())
    latency = json.loads((a.work/'latency_results/results.json').read_text())
    latency_rows = []
    for clip in latency['clips']:
        audio = Path(clip['audio'])
        add(audio,'research/whisper-latency/audio/'+audio.name)
        source_manifest = audio.parent.parent/'evaluation.jsonl'
        references = [json.loads(line) for line in source_manifest.read_text().splitlines() if line.strip()]
        row = next(row for row in references if Path(row['audio']).name==audio.name)
        latency_rows.append(dict(row,audio='audio/'+audio.name))
    files['research/whisper-latency/evaluation.jsonl'] = ''.join(json.dumps(row)+'\n' for row in latency_rows).encode()
    add(Path(latency['clips'][0]['audio']).parent.parent/'PROVENANCE.json','research/whisper-latency/PROVENANCE.json')
    entries = {}
    a.out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(a.out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,path in sorted(files.items()):
            data = path if isinstance(path,bytes) else path.read_bytes()
            entries[name] = {'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (0o100755 if Path(name).name=='whisper-cli' else 0o100644)<<16
            info.compress_type = zipfile.ZIP_STORED if name.startswith('ggml-') and len(data)>128*1024*1024 else zipfile.ZIP_DEFLATED
            archive.writestr(info,data,compresslevel=6)
        manifest = {'format':1,'name':f'kv260-whisper-{short}-prototype','version':'0.2.0' if short=='large-v3-turbo' else '0.1.0',
                    'upstream_commit':'2eeeba56e9edd762b4b38467bab96c2517163158',
                    'kernel':kernel,'model':identity,'files':entries}
        archive.writestr('WHISPER_MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(a.out) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('Archive CRC verification failed')
        for name,entry in entries.items():
            if hashlib.sha256(archive.read(name)).hexdigest()!=entry['sha256']:
                raise RuntimeError('Archive SHA256 verification failed: '+name)
    with a.out.open('rb') as f:
        checksum = hashlib.file_digest(f,'sha256').hexdigest()
    a.out.with_suffix(a.out.suffix+'.sha256').write_text(checksum+'  '+a.out.name+'\n')
    print(json.dumps({'archive':str(a.out),'files':len(entries),'sha256':checksum,'bytes':a.out.stat().st_size},indent=2))


if __name__ == '__main__':
    main()
