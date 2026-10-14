"""Preserve a new immutable overlay of retained-pair sources and evidence."""
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
    parent=read(a.parent.parent/'short-package.json');assert sha(a.parent)==parent['archive_sha256']
    r=ROOT/'reports/fused'
    for name in ('pair_native_oracle_validation.json','pair_native_synthetic.json','depthwise_pair_validation.json'):
        proof=read(r/name);assert proof['complete']
    numerical=read(r/'pair_native_oracle_validation.json')
    assert numerical['library_sha256']==sha(ROOT/'software/ort_fpga_pair/libort_fpga.so')
    assert numerical['source_sha256']==sha(ROOT/'software/ort_fpga_pair/validate.py')
    assert numerical['graph_source_sha256']==sha(ROOT/'software/ort_fpga_pair/graph.py')
    assert numerical['errors']['cpu']==numerical['errors']['oracle']
    assert 'PASS: 19 fused depthwise/pointwise arithmetic' in (r/'fused_pair_sim.log').read_text()
    assert 'PASS: 256 real checkpoint depthwise channels' in (r/'depthwise_model_sim.log').read_text()
    assert 'PASS: 13 depthwise channel arithmetic' in (r/'depthwise_channel_sim.log').read_text()
    physical=False
    if a.phase=='physical':
        proof=read(r/'pair_physical_validation.json');assert proof['complete'] and proof['hardware_execution']
        physical=True
    files=list((ROOT/'software/ort_fpga_pair').glob('*.py'))+list((ROOT/'software/ort_fpga_pair').glob('*.cc'))
    files+=list((ROOT/'software/ort_fpga_pair').glob('*.c'))+list((ROOT/'software/ort_fpga_pair').glob('*.h'))
    files+=list((ROOT/'software/ort_fpga_pair/include').glob('*.h'))
    files += [ROOT/'software/ort_fpga_pair'/n for n in ('build.sh','README.md','libort_fpga.so')]
    for directory in ('deployment/experimental-pair','deployment/asr-v3-pair'):
        files += [p for p in (ROOT/directory).iterdir() if p.is_file()]
    files += [ROOT/'rtl/experimental'/n for n in ('qn_fused_axis.sv','qn_fused_core.v','fused_depthwise_channel.sv','fused_affine_quant.v')]
    files += [ROOT/'sim'/n for n in ('tb_qn_fused_axis.sv','tb_fused_depthwise_channel.sv','tb_depthwise_model.sv')]
    files += [ROOT/'scripts'/n for n in ('fused_system_build.tcl','fused_pair_sim.tcl','depthwise_channel_sim.tcl',
                                       'depthwise_model_sim.tcl','generate_depthwise_model_tb.py','generate_fused_pair_tb.py',
                                       'extend_pair_driver.py','prepare_pair_firmware.py','vivado_four_threads.tcl','save_pair_progress.py')]
    files += [ROOT/'scripts/run_pair_physical.sh',ROOT/'scripts/run_pair_cpu_threads.sh',
              ROOT/'scripts/install_pair_firmware.sh']
    files += [ROOT/'software/latency/profile_blocks.py',ROOT/'software/latency/validate_depthwise_pair.py']
    for pattern in ('pair_*.json','pair_*.log','pair_*.onnx','depthwise_*.json','depthwise_*_sim.log',
                    'fused_pair_sim.log','fused_system_*.rpt','fused_system_*.json','fused_system_build.log'):
        files += list(r.glob(pattern))
    for name in ('block_half_profile.json','block_one_profile.json'):
        files += [r/name,r/Path(read(r/name)['trace']).name]
    files += list((r/'depthwise_pair_vectors').iterdir())
    files += [ROOT/'FUSED_PAIR_PROGRESS.md']
    # A running build may append to its log while packaging; freeze each file's
    # bytes first so the archive and manifest describe the same checkpoint.
    payloads={p.relative_to(ROOT).as_posix():p.read_bytes() for p in sorted(set(files)) if p.is_file()}
    digests={rel:hashlib.sha256(data).hexdigest() for rel,data in payloads.items()}
    a.destination.mkdir(parents=True);archive=a.destination/'fused-pair-progress.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for rel,data in payloads.items():z.writestr(rel,data)
    with zipfile.ZipFile(archive) as z:
        for rel,digest in digests.items():assert hashlib.sha256(z.read(rel)).hexdigest()==digest
    manifest={'archive':archive.name,'archive_sha256':sha(archive),'files':digests,
              'parent_archive':str(a.parent),'parent_sha256':sha(a.parent),'phase':a.phase,
              'hardware_execution_validated':physical,'latency_improvement_claimed':False,
              'restore':'Restore hardware and CSE parents listed by the short-input parent, then short-input parent, then this overlay.',
              'accepted_bulk_artifacts_preserved':True,'representative_corpus_qualified':False}
    (a.destination/'pair-package.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    shutil.copy2(ROOT/'FUSED_PAIR_PROGRESS.md',a.destination/'FUSED_PAIR_PROGRESS.md')
    print(json.dumps({'directory':str(a.destination),'sha256':manifest['archive_sha256'],'files':len(digests),'phase':a.phase}))


if __name__=='__main__':main()
