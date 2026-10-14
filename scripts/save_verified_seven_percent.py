"""Consolidate the verified 7.3%/7.9% runtime, model and immutable evidence."""
import argparse,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
ap=argparse.ArgumentParser();ap.add_argument('--destination',type=Path,required=True);a=ap.parse_args()
assert not a.destination.exists()
downloads=Path.home()/'Downloads'
manifest=downloads/'FPGA-ASR-short-cache-scheduled-physical-2026-10-11/scheduled-short-cache-package.json'
chain=[]
while True:
    proof=read(manifest);archive=manifest.parent/proof['archive']
    assert sha(archive)==proof['archive_sha256']
    chain.append((manifest,archive,proof))
    parent=proof.get('parent_archive')
    if not parent:break
    archive=Path(parent);assert sha(archive)==proof['parent_sha256']
    matches=[p for p in archive.parent.glob('*package.json') if read(p).get('archive')==archive.name]
    assert len(matches)==1;manifest=matches[0]
payload={};origins=[]
for manifest,archive,proof in reversed(chain):
    with zipfile.ZipFile(archive) as z:
        for name,digest in proof['files'].items():
            value=z.read(name);assert hashlib.sha256(value).hexdigest()==digest
            if any(token in name.lower() for token in ('short_wide','short-wide','shortwide')):continue
            payload[name]=value
    origins.append({'archive':str(archive),'sha256':sha(archive)})
paths=[]
for folder in ('software/fused','software/ort_fpga_bulk','deployment/experimental-bulk','deployment/asr-v3-bulk'):
    paths += [p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
for folder in ('research/export/citrinet-256-ls','research/eval/user-recording','research/eval/librispeech-mini','research/eval/user-stress-ac'):
    paths += [p for p in (ROOT/folder).rglob('*') if p.is_file()]
paths += [ROOT/'research/fused'/name for name in ('cpu-int8-cse.onnx','cpu-int8-cse.json','cpu-int8.onnx','cpu-int8.json')]
paths += [ROOT/'reports/fused/cse_arm_validation.json',ROOT/'reports/old/nemo_full_validation.json',ROOT/'research/checkpoints/citrinet-256-ls/stt_en_citrinet_256_ls.nemo',ROOT/'software/model-tools/citrinet_cpu.py',ROOT/'software/evaluation/benchmark.py',ROOT/'software/latency/resident.py',Path(__file__)]
for path in paths:
    name=path.relative_to(ROOT).as_posix();value=path.read_bytes()
    if name in payload:assert payload[name]==value,('Protected parent file differs',name)
    payload[name]=value
summary=read(ROOT/'reports/fused/shortcache_scheduled_summary.json')
assert summary['complete'] and summary['whole_model_latency_accepted']
for name,digest in summary['evidence_sha256'].items():assert hashlib.sha256(payload[name]).hexdigest()==digest
physical=read(ROOT/'reports/fused/shortcache_physical_validation.json')
for name,key in [('software/ort_fpga_shortcache/libort_fpga.so','library_sha256'),('deployment/experimental-shortcache/qn_tile.ko','driver_sha256'),('deployment/asr-v3-shortcache/asr-v3-shortcache.bit.bin','firmware_sha256')]:assert hashlib.sha256(payload[name]).hexdigest()==physical[key]
payload['RESTORE_7_PERCENT.md']=b'''# Verified short-input FPGA version\n\nThis consolidated runtime archive preserves the 7.31% gain at 0.5 s and 7.90% at 1 s. It includes firmware, driver, native library, exact model/frontend/checkpoint, diagnostic WAVs, source and paired measurement evidence. The wider-depthwise experiment is excluded.\n\nExtract into the board project root (/home/ubuntu/prototype-v3-fused) in a separate restored checkout. The tested environment is ARM64 Ubuntu with its existing qn_tile-compatible kernel, xmutil, Python 3.12, NumPy 2.5, ONNX 1.23 and ONNX Runtime 1.30. The OS and Python environment are separate dependencies.\n\nInstall with scripts/install_short_cache_firmware.sh as root. scripts/run_short_cache_scheduled_resident.sh activates the retained image, tests both scheduled resident API contexts, and restores accepted bulk firmware on exit. The scheduled API is software/latency/short_cache_scheduled_resident.py. Proofs are reports/fused/shortcache_scheduled_half.json and shortcache_scheduled_one.json; these bind matching .onnx graphs and the worker/IRQ policies.\n\nThe graph accelerates 32 pairs (64 convolutions). FPGA windows are limited to 2.55 s. Results are warm latency measurements including frontend, graph execution, transfers and decoding. Diagnostic parity passed; representative corpus accuracy and live capture remain unqualified. The 10% target remains unmet for this saved version.\n'''
a.destination.mkdir(parents=True);archive=a.destination/'verified-short-cache-7pct.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name,value in sorted(payload.items()):z.writestr(name,value)
with zipfile.ZipFile(archive) as z:
    for name,value in payload.items():assert z.read(name)==value
manifest={'archive':archive.name,'archive_sha256':sha(archive),'files':{n:hashlib.sha256(v).hexdigest() for n,v in payload.items()},'source_checkpoints':origins,
          'hardware_execution_validated':True,'whole_model_latency_accepted':True,'ten_percent_latency_accepted':False,
          'contexts':summary['contexts'],'wider_experiment_included':False,'representative_corpus_qualified':False,'capture_tested':False}
(a.destination/'verified-package.json').write_text(json.dumps(manifest,indent=2)+'\n')
(a.destination/'RESTORE_7_PERCENT.md').write_bytes(payload['RESTORE_7_PERCENT.md'])
(a.destination/'RESULTS.md').write_bytes(payload['SHORT_CACHE_SCHEDULE_RESULTS.md'])
print(json.dumps({'archive':str(archive),'sha256':sha(archive),'files':len(payload)}))
