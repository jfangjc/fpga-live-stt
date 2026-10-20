"""Save longer-window results as an immutable overlay of verified wider firmware."""
import argparse,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
ap=argparse.ArgumentParser();ap.add_argument('--destination',type=Path,required=True);a=ap.parse_args()
assert not a.destination.exists()
parent=Path.home()/'Downloads/FPGA-ASR-short-wide-physical-2026-10-11/short-wide-progress.zip'
manifest=json.loads((parent.parent/'short-wide-package.json').read_text())
assert manifest['hardware_execution_validated'] and manifest['whole_model_latency_accepted'] and sha(parent)==manifest['archive_sha256']
proof=json.loads((ROOT/'reports/fused/shortwide_long_summary.json').read_text())
assert proof['complete'] and proof['hardware_execution'] and all(r['latency_accepted'] for r in proof['contexts'])
for name,digest in proof['evidence_sha256'].items():assert sha(ROOT/name)==digest
files=[ROOT/'LONG_INPUT_RESULTS.md',ROOT/'software/latency/test_short_wide_long_inputs.py']
files += list((ROOT/'reports/fused').glob('shortwide_long*'))
files += [ROOT/'scripts'/name for name in ('create_long_input_test.py','run_short_wide_long_inputs.sh','verify_short_wide_long_restoration.py','summarize_long_input_test.py',Path(__file__).name)]
payload={p.relative_to(ROOT).as_posix():p.read_bytes() for p in sorted(set(files))}
a.destination.mkdir(parents=True);archive=a.destination/'long-input-results.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name,value in payload.items():z.writestr(name,value)
with zipfile.ZipFile(archive) as z:
    for name,value in payload.items():assert z.read(name)==value
(a.destination/'long-input-package.json').write_text(json.dumps({'archive':archive.name,'archive_sha256':sha(archive),
    'files':{n:hashlib.sha256(v).hexdigest() for n,v in payload.items()},'parent_archive':str(parent),'parent_sha256':sha(parent),
    'hardware_execution_validated':True,'maximum_input_seconds':2.55,'runs_per_context':100,
    'representative_corpus_qualified':False,'capture_tested':False},indent=2)+'\n')
(a.destination/'LONG_INPUT_RESULTS.md').write_bytes((ROOT/'LONG_INPUT_RESULTS.md').read_bytes())
print(json.dumps({'archive':str(archive),'sha256':sha(archive),'files':len(payload)}))
