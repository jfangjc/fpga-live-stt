"""Archive confirmed scheduling as an immutable overlay of the physical checkpoint."""
import argparse,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
ap=argparse.ArgumentParser();ap.add_argument('--destination',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True);a=ap.parse_args()
assert not a.destination.exists()
parent=json.loads((a.parent.parent/'short-cache-package.json').read_text())
assert parent['hardware_execution_validated'] and sha(a.parent)==parent['archive_sha256']
proof=json.loads((ROOT/'reports/fused/shortcache_scheduled_summary.json').read_text())
assert proof['complete'] and proof['whole_model_latency_accepted']
for name,value in proof['evidence_sha256'].items():assert sha(ROOT/name)==value
files=[ROOT/'SHORT_CACHE_SCHEDULE_RESULTS.md',ROOT/'reports/fused/shortcache_schedule_screen.json',ROOT/'reports/fused/shortcache_scheduled_summary.json']
files+=list((ROOT/'reports/fused').glob('shortcache_scheduled_*.json'))+list((ROOT/'reports/fused').glob('shortcache_scheduled_*.onnx'))
files+=list((ROOT/'software/latency').glob('*short*cache*schedule*.py'))
files += [ROOT/'scripts'/name for name in ('create_short_cache_confirmation.py','create_scheduled_resident.py','summarize_short_cache_schedule.py','run_short_cache_schedule.sh','run_short_cache_confirmation.sh','run_short_cache_scheduled_resident.sh','verify_short_cache_scheduled_restoration.py',Path(__file__).name)]
files += [ROOT/'scripts'/name for name in ('build_short_wide_sources.py','short_wide_sim.tcl','short_wide_synth.tcl')]
files += [ROOT/'rtl/experimental'/name for name in ('qn_short_wide_axis.sv','fused_depthwise_channel_wide.sv')]
payload={p.relative_to(ROOT).as_posix():p.read_bytes() for p in sorted(set(files))}
a.destination.mkdir(parents=True);archive=a.destination/'scheduled-short-cache-progress.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name,value in payload.items():z.writestr(name,value)
with zipfile.ZipFile(archive) as z:
    for name,value in payload.items():assert z.read(name)==value
manifest={'archive':archive.name,'archive_sha256':sha(archive),'files':{n:hashlib.sha256(v).hexdigest() for n,v in payload.items()},
          'parent_archive':str(a.parent),'parent_sha256':sha(a.parent),'hardware_execution_validated':True,
          'whole_model_latency_accepted':True,'ten_percent_latency_accepted':proof['ten_percent_latency_accepted'],
          'wider_depthwise_hardware_validated':False,'representative_corpus_qualified':False,'capture_tested':False,
          'restore':'Restore the physical short-cache parent and its parents, then this overlay. Wider RTL is an unvalidated development experiment.'}
(a.destination/'scheduled-short-cache-package.json').write_text(json.dumps(manifest,indent=2)+'\n')
(a.destination/'SHORT_CACHE_SCHEDULE_RESULTS.md').write_bytes((ROOT/'SHORT_CACHE_SCHEDULE_RESULTS.md').read_bytes())
print(json.dumps({'archive':str(archive),'sha256':sha(archive),'files':len(payload)}))
