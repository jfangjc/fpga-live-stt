"""Save an immutable short-cache overlay, preserving its physically verified parent."""
import argparse,hashlib,json,shutil,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--destination',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True)
    ap.add_argument('--phase',choices=('development','physical'),default='development');a=ap.parse_args()
    assert not a.destination.exists()
    parent=read(a.parent.parent/'cache-package.json')
    assert sha(a.parent)==parent['archive_sha256'] and parent['hardware_execution_validated'] and parent['whole_model_latency_accepted']
    old=read(ROOT/'reports/fused/cache_physical_validation.json')
    for name,key in [('software/ort_fpga_cache/libort_fpga.so','library_sha256'),
                     ('deployment/experimental-cache/qn_tile.ko','driver_sha256'),
                     ('deployment/asr-v3-cache/asr-v3-cache.bit.bin','firmware_sha256')]:assert sha(ROOT/name)==old[key]
    physical=a.phase=='physical'
    if physical:
        proof=read(ROOT/'reports/fused/shortcache_result_summary.json')
        assert proof['complete'] and proof['hardware_execution']
    files=[]
    for folder in ('software/ort_fpga_shortcache','deployment/experimental-shortcache','deployment/asr-v3-shortcache'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    for pattern in ('shortcache_*.json','shortcache_*.log','shortcache_*.onnx','shortcache_*.py','short_cache_*.log','short_cache_*.rpt','short_cache_*.json'):
        files.extend((ROOT/'reports/fused').glob(pattern))
    files.extend((ROOT/'scripts').glob('*short*cache*.*'))
    files.extend([ROOT/'rtl/experimental/qn_short_cache_core.v',ROOT/'rtl/experimental/qn_short_cache_axis.sv',
                  ROOT/'rtl/experimental/fused_depthwise_channel.sv',ROOT/'rtl/experimental/fused_affine_quant.v',
                  ROOT/'sim/tb_qn_short_cache_axis.sv',ROOT/'SHORT_CACHE_PROGRESS.md'])
    if (ROOT/'SHORT_CACHE_RESULTS.md').exists():files.append(ROOT/'SHORT_CACHE_RESULTS.md')
    data={p.relative_to(ROOT).as_posix():p.read_bytes() for p in sorted(set(files)) if p.is_file()}
    hashes={name:hashlib.sha256(value).hexdigest() for name,value in data.items()}
    a.destination.mkdir(parents=True);archive=a.destination/'short-cache-progress.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in data.items():z.writestr(name,value)
    with zipfile.ZipFile(archive) as z:
        for name,digest in hashes.items():assert hashlib.sha256(z.read(name)).hexdigest()==digest
    manifest={'archive':archive.name,'archive_sha256':sha(archive),'files':hashes,'phase':a.phase,
              'parent_archive':str(a.parent),'parent_sha256':sha(a.parent),'hardware_execution_validated':physical,
              'ten_percent_latency_accepted':proof['ten_percent_latency_accepted'] if physical else False,
              'restore':'Restore the verified four-pair parent and its parents, then this overlay.',
              'representative_corpus_qualified':False,'capture_tested':False}
    (a.destination/'short-cache-package.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    shutil.copy2(ROOT/'SHORT_CACHE_PROGRESS.md',a.destination/'SHORT_CACHE_PROGRESS.md')
    print(json.dumps({'directory':str(a.destination),'sha256':manifest['archive_sha256'],'files':len(data),'phase':a.phase}))

if __name__=='__main__':main()
