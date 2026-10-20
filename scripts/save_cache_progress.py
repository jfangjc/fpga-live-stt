"""Save a new immutable cache experiment overlay, with its verified parent."""
import argparse,hashlib,json,shutil,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--destination',type=Path,required=True)
    ap.add_argument('--parent',type=Path,required=True)
    ap.add_argument('--phase',choices=('development','physical'),default='development')
    a=ap.parse_args();assert not a.destination.exists()
    parent=read(a.parent.parent/'pair-package.json');assert sha(a.parent)==parent['archive_sha256']
    assert parent['hardware_execution_validated']
    r=ROOT/'reports/fused';runtime=ROOT/'software/ort_fpga_cache'
    oracle=read(r/'cache_native_oracle_validation.json');synthetic=read(r/'cache_native_synthetic.json')
    assert oracle['complete'] and synthetic['complete'] and synthetic['exact_numpy_parity']
    assert oracle['errors']['cpu']==oracle['errors']['oracle']
    assert oracle['library_sha256']==synthetic['library_sha256']==sha(runtime/'libort_fpga.so')
    assert oracle['source_sha256']==sha(runtime/'validate.py')
    assert oracle['graph_source_sha256']==sha(runtime/'graph.py')
    assert 'PASS: 36912 cache slot packet' in (r/'cache_driver_protocol.log').read_text()
    assert 'PASS: four-slot transport residency' in (r/'cache_transport.log').read_text()
    physical=a.phase=='physical'
    if physical:
        assert 'PASS: 26 four-slot retained pair arithmetic' in (r/'pair_cache_sim.log').read_text()
        report=read(r/'cache_physical_validation.json');assert report['complete'] and report['hardware_execution']
        assert report['library_sha256']==sha(runtime/'libort_fpga.so')
    files=[]
    for folder in ('software/ort_fpga_cache','deployment/experimental-cache','deployment/asr-v3-cache'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    files.extend(ROOT/'rtl/experimental'/name for name in ('qn_pair_cache_axis.sv','qn_pair_cache_core.v','fused_depthwise_channel.sv','fused_affine_quant.v'))
    files.extend(ROOT/'scripts'/name for name in ('build_pair_cache_sources.py','pair_cache_sim.tcl','pair_cache_system_build.tcl','prepare_cache_firmware.py','run_cache_physical.sh','save_cache_progress.py','summarize_cache_results.py','verify_cache_restoration.py','vivado_four_threads.tcl'))
    installer=ROOT/'scripts/install_cache_firmware.sh'
    if installer.exists():files.append(installer)
    files.extend([ROOT/'sim/tb_qn_pair_cache_axis.sv',ROOT/'CACHE_PROGRESS.md'])
    if (ROOT/'CACHE_RESULTS.md').exists():files.append(ROOT/'CACHE_RESULTS.md')
    for pattern in ('cache_*.json','cache_*.log','cache_*.onnx','pair_cache_*.log','pair_cache_*.json','pair_cache_*.rpt'):
        files.extend(r.glob(pattern))
    payloads={p.relative_to(ROOT).as_posix():p.read_bytes() for p in sorted(set(files)) if p.is_file()}
    hashes={name:hashlib.sha256(data).hexdigest() for name,data in payloads.items()}
    a.destination.mkdir(parents=True);archive=a.destination/'four-pair-cache-progress.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in payloads.items():z.writestr(name,data)
    with zipfile.ZipFile(archive) as z:
        for name,digest in hashes.items():assert hashlib.sha256(z.read(name)).hexdigest()==digest
    manifest={'archive':archive.name,'archive_sha256':sha(archive),'files':hashes,'phase':a.phase,
              'parent_archive':str(a.parent),'parent_sha256':sha(a.parent),
              'hardware_execution_validated':physical,
              'whole_model_latency_accepted':read(r/'cache_result_summary.json')['whole_model_latency_accepted'] if physical else False,
              'restore':'Restore the verified single-pair parent and its parents, then this overlay.',
              'representative_corpus_qualified':False,'capture_tested':False}
    (a.destination/'cache-package.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    shutil.copy2(ROOT/'CACHE_PROGRESS.md',a.destination/'CACHE_PROGRESS.md')
    print(json.dumps({'directory':str(a.destination),'sha256':manifest['archive_sha256'],'files':len(hashes),'phase':a.phase}))


if __name__=='__main__':main()
