"""Save validated short-input profiles as an immutable overlay of prior work."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--destination',type=Path,required=True)
    ap.add_argument('--cse-base',type=Path,required=True)
    ap.add_argument('--hardware-base',type=Path,required=True)
    a=ap.parse_args()
    assert not a.destination.exists(), 'Use a new snapshot directory'
    parent=read(a.cse_base.parent/'cse-package.json')
    assert sha(a.cse_base)==parent['archive_sha256']
    assert sha(a.hardware_base)==parent['base_sha256']
    smoke=read(ROOT/'reports/fused/short_resident_smoke.json')
    assert smoke['complete'] and smoke['caller_affinity_restored'] and smoke['nonfinite_input_rejected']
    assert smoke['resident_source_sha256']==sha(ROOT/'software/latency/resident.py')
    proofs=[]
    for label,name in [('half','short_half_second_deployment.json'),('one','short_one_second_irq3_deployment.json')]:
        path=ROOT/'reports/fused'/name; p=read(path)
        assert p['complete'] and p['hardware_execution'] and p['runs']>=100
        assert sha(path.with_suffix('.onnx'))==p['fpga_graph_sha256']
        assert sha(path)==smoke['profile_sha256'][label]
        assert p['binding_source_sha256']==sha(ROOT/'software/latency/bind_short_profile.py')
        assert sha(ROOT/'research/fused/cpu-int8-cse.onnx')==p['cpu_model_sha256']
        physical_path=ROOT/p['physical_validation_relative_path']; physical=read(physical_path)
        assert sha(physical_path)==p['physical_validation_sha256']
        assert physical['complete'] and physical['nodes']==p['nodes'] and physical['wer_degradation_percentage_points']<=1
        assert all(c['physical_oracle_bit_parity'] and c['within_tolerance'] and c['length_exact'] for c in physical['clips'])
        for key,rel in [('library_sha256','software/ort_fpga_bulk/libort_fpga.so'),
                        ('firmware_sha256','deployment/asr-v3-bulk/asr-v3-bulk.bit.bin')]:
            assert sha(ROOT/rel)==p[key]
        if label=='half':
            assert all(c['mean_saving_95ci_seconds'][0]>0 and c['fpga_p50']<c['cpu_p50'] and
                       c['fpga_p95']<c['cpu_p95'] for c in p['contexts'])
            assert all(r['results']['fpga']['fpga_counters']['loads']==0 and
                       r['results']['fpga']['fpga_counters']['ioctls']==1 for r in p['paired_runs'])
        else:
            assert p['runs']==300 and p['dma_irq_core']==3
        proofs.append(p)
    files=list((ROOT/'software/latency').glob('*.py'))+list((ROOT/'software/latency/accepted_sources').glob('*.py'))
    files += list((ROOT/'scripts').glob('run_short*.sh'))
    files += [Path(__file__).resolve(),ROOT/'scripts/update_short_results.py',
              ROOT/'scripts/preserve_static_screen_source.py',ROOT/'software/latency/README.md',
              ROOT/'SHORT_INPUT_RESULTS.md',ROOT/'LIVE_PLAN.md']
    files += list((ROOT/'reports/fused').glob('short*.json'))
    files += [ROOT/'reports/fused/cse_resident_smoke.json']
    files += [ROOT/'reports/fused/short_half_second_deployment.onnx',
              ROOT/'reports/fused/short_one_second_irq3_deployment.onnx']
    digests={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(set(files))}
    a.destination.mkdir(parents=True)
    archive=a.destination/'short-input-progress.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for rel in digests:
            z.write(ROOT/rel,rel)
            target=a.destination/'project'/rel;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/rel,target)
    with zipfile.ZipFile(archive) as z:
        for rel,digest in digests.items():
            assert hashlib.sha256(z.read(rel)).hexdigest()==digest==sha(a.destination/'project'/rel)
    manifest={'archive':archive.name,'archive_sha256':sha(archive),'files':digests,
              'parents':[{'archive':str(a.hardware_base),'sha256':sha(a.hardware_base)},
                         {'archive':str(a.cse_base),'sha256':sha(a.cse_base)}],
              'restore':'Extract six-operator hardware base, then CSE overlay, then this short-input overlay.',
              'capture_tested':False,'representative_corpus_qualified':False,
              'half_second_profile':'One resident FPGA layer; nonspinning four-thread CPU; trimmed padding',
              'one_second_profile':'Six physical layers; 10-us worker spin; trimmed padding; explicit DMA IRQ core 3',
              'previous_snapshots_preserved':True}
    (a.destination/'short-package.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    shutil.copy2(ROOT/'SHORT_INPUT_RESULTS.md',a.destination/'SHORT_INPUT_RESULTS.md')
    print(json.dumps({'directory':str(a.destination),'sha256':manifest['archive_sha256'],'files':len(digests)}))


if __name__=='__main__':main()
