"""Add a verified, source-complete Vivado companion without changing snapshots."""
import argparse,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--destination',type=Path,required=True);a=ap.parse_args()
meta=json.loads((a.destination/'package.json').read_text());assert meta['verified']
sha=lambda b:hashlib.sha256(b).hexdigest()
assert sha(Path(meta['archive']).read_bytes())==meta['sha256']
archive=a.destination/'vivado-project-sources.zip';assert not archive.exists()
project=ROOT/'build/stream_system';payload={}
paths=[project/'Prototype_v3_stream.xpr']
for folder in ('Prototype_v3_stream.srcs','Prototype_v3_stream.gen'):
    paths.extend(p for p in (project/folder).rglob('*') if p.is_file() and p.suffix.lower() in
                 ('.v','.sv','.vhd','.vh','.svh','.xdc','.bd','.xci','.tcl','.coe','.mem','.xml'))
assert any(p.suffix=='.bd' for p in paths)
for p in paths:payload[p.relative_to(ROOT).as_posix()]=p.read_bytes()
readme='''# Restore the working Vivado project

Extract fpga-asr-latency-work.zip and vivado-project-sources.zip into the same
separate directory, preserving paths. The companion includes the complete
working build/stream_system/Prototype_v3_stream.xpr, its block design,
constraints and small generated HDL sources. The root Prototype_v2.xpr
currently has an empty sources list; use the working stream project.

Vivado 2026.1 can regenerate IP outputs using scripts/stream_synth.tcl and
scripts/stream_implement.tcl. The adaptive builder clones this working stream
project into build/adaptive_system_v2. Tool installations and board Python
dependencies are external. Consult LATENCY20_PROGRESS.md and the selected
paired benchmark report for qualification and limitations.

The original measured snapshot ZIP and package.json are unchanged. The
companion manifest binds its files and the original snapshot SHA256.
'''
payload['RESTORE_VIVADO_PROJECT.md']=readme.encode()
manifest={'complete':True,'original_snapshot_sha256':meta['sha256'],
          'files_sha256':{name:sha(data) for name,data in sorted(payload.items())}}
payload['VIVADO_PROJECT_SOURCE_MANIFEST.json']=(json.dumps(manifest,indent=2)+'\n').encode()
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name,data in sorted(payload.items()):z.writestr(name,data)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None and set(z.namelist())==set(payload)
    for name,data in payload.items():assert sha(z.read(name))==sha(data)
metadata={'archive':str(archive),'sha256':sha(archive.read_bytes()),'files':len(payload),
          'bytes':archive.stat().st_size,'verified':True,'original_snapshot_sha256':meta['sha256']}
(a.destination/'vivado-project-package.json').write_text(json.dumps(metadata,indent=2)+'\n')
(a.destination/'RESTORE_VIVADO_PROJECT.md').write_text(readme)
print(json.dumps(metadata))
