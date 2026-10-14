"""Create an immutable wider-depthwise overlay with explicit validation state."""
import argparse,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
ap=argparse.ArgumentParser();ap.add_argument('--destination',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True)
ap.add_argument('--phase',choices=('development','physical'),default='development');a=ap.parse_args()
assert not a.destination.exists()
parent=read(a.parent.parent/'scheduled-short-cache-package.json')
assert parent['hardware_execution_validated'] and parent['whole_model_latency_accepted'] and sha(a.parent)==parent['archive_sha256']
freeze=read(ROOT/'reports/fused/shortwide_source_freeze.json')
for name,value in freeze['sources_sha256'].items():assert sha(ROOT/name)==value
native=read(ROOT/'reports/fused/shortwide_native_oracle_validation.json')
assert native['complete'] and native['all_prefix_transcripts_exact'] and native['diagnostic_wer_delta_percentage_points']<=1
physical=a.phase=='physical';summary=read(ROOT/'reports/fused/shortwide_scheduled_summary.json') if physical else None
if physical:
    assert summary['complete'] and summary['hardware_execution']
    for name,value in summary['evidence_sha256'].items():assert sha(ROOT/name)==value
files=[ROOT/'SHORT_WIDE_PROGRESS.md']
files += [p for folder in ('software/ort_fpga_shortwide','deployment/experimental-shortwide','deployment/asr-v3-shortwide') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
files += list((ROOT/'scripts').glob('*short*wide*.*'))+list((ROOT/'software/latency').glob('*short*wide*.py'))
files += [ROOT/name for name in freeze['sources_sha256']]
files += list((ROOT/'reports/fused').glob('shortwide_native_*'))+[ROOT/'reports/fused/shortwide_source_freeze.json']
if physical:
    files += list((ROOT/'reports/fused').glob('shortwide_*'))+list((ROOT/'reports/fused').glob('short_wide_*.rpt'))+list((ROOT/'reports/fused').glob('short_wide_*.log'))+list((ROOT/'reports/fused').glob('short_wide_*.json'))+[ROOT/'SHORT_WIDE_RESULTS.md']
payload={p.relative_to(ROOT).as_posix():p.read_bytes() for p in sorted(set(files))}
a.destination.mkdir(parents=True);archive=a.destination/'short-wide-progress.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name,value in payload.items():z.writestr(name,value)
with zipfile.ZipFile(archive) as z:
    for name,value in payload.items():assert z.read(name)==value
manifest={'archive':archive.name,'archive_sha256':sha(archive),'files':{n:hashlib.sha256(v).hexdigest() for n,v in payload.items()},
          'parent_archive':str(a.parent),'parent_sha256':sha(a.parent),'phase':a.phase,'hardware_execution_validated':physical,
          'whole_model_latency_accepted':summary['whole_model_latency_accepted'] if physical else False,
          'ten_percent_latency_accepted':summary['ten_percent_latency_accepted'] if physical else False,
          'representative_corpus_qualified':False,'capture_tested':False,
          'restore':'Restore the confirmed scheduling parent and its parents, then this separate wider-depthwise overlay.'}
(a.destination/'short-wide-package.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'archive':str(archive),'sha256':sha(archive),'files':len(payload),'phase':a.phase}))
