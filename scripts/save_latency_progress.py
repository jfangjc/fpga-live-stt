"""Save a hash-bound latency overlay without altering verified snapshots."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--destination', type=Path, required=True)
    ap.add_argument('--base', type=Path, required=True)
    a = ap.parse_args()
    base = json.loads((ROOT/'reports/fused/bulk_six_package.json').read_text())
    if sha(a.base) != base['sha256']:
        raise ValueError('Verified base archive identity mismatch')
    proof_path = ROOT/'reports/fused/context_spin1000_confirmation100.json'
    proof = json.loads(proof_path.read_text())
    short = json.loads((ROOT/'reports/fused/context_half_second_threads2_100.json').read_text())
    for p in (proof, short):
        assert p['complete'] and p['runs'] == 100 and p['hardware_execution']
        assert all(c['physical_oracle_bit_parity'] for c in p['contexts'])
    assert proof['cpu_threads'] == 4 and proof['spin_duration_us'] == 1000
    assert all(c['mean_saving_95ci_seconds'][0] > 0 and c['fpga_p50'] < c['cpu_p50']
               for c in proof['contexts'])
    assert sha(proof_path.with_suffix('.onnx')) == proof['fpga_graph_sha256']
    for key, rel in [('cpu_model_sha256','research/fused/cpu-int8.onnx'),
                     ('library_sha256','software/ort_fpga_bulk/libort_fpga.so'),
                     ('firmware_sha256','deployment/asr-v3-bulk/asr-v3-bulk.bit.bin')]:
        assert sha(ROOT/rel) == proof[key] == base['files'][rel]
    for backend in ('fpga', 'cpu'):
        rows = [json.loads(v) for v in (ROOT/f'reports/fused/latency_resident_{backend}.jsonl').read_text().splitlines()]
        assert len(rows) == 4
        for row in rows[1:]:
            assert row['backend'] == backend
            if backend == 'fpga':
                assert row['fpga_counters']['physical_calls'] == len(proof['nodes'])
                assert row['fpga_counters']['oracle_calls'] == 0
    files = list((ROOT/'software/latency').glob('*.py')) + [ROOT/'software/latency/README.md']
    files += [ROOT/'LATENCY_RESULTS.md',ROOT/'LIVE_PLAN.md',ROOT/'RESULTS_V3.md',ROOT/'PLAN_V3.md',Path(__file__).resolve(),
              ROOT/'scripts/run_latency_confirmation.sh',ROOT/'scripts/run_latency_profile_policy.sh',
              ROOT/'scripts/run_latency_resident_smoke.sh']
    files += list((ROOT/'reports/fused').glob('context*.json'))
    files += list((ROOT/'reports/fused').glob('shared_shape*validation.json'))
    files += list((ROOT/'reports/fused').glob('sparse_frontend*validation.json'))
    files += list((ROOT/'reports/fused').glob('latency_resident_*.jsonl'))
    files += [proof_path.with_suffix('.onnx')]
    a.destination.mkdir(parents=True, exist_ok=True)
    archive = a.destination/'latency-progress.zip'
    hashes = {}
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(set(files)):
            rel = p.relative_to(ROOT).as_posix()
            hashes[rel] = sha(p)
            z.write(p, rel)
            target = a.destination/'project'/rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
    with zipfile.ZipFile(archive) as z:
        for rel, digest in hashes.items():
            assert hashlib.sha256(z.read(rel)).hexdigest() == digest
    manifest = {'archive': archive.name, 'archive_sha256': sha(archive),
                'files': hashes, 'base_archive': a.base.name, 'base_sha256': base['sha256'],
                'instructions': 'Extract the verified six-operator base first, then this overlay into the same project root.',
                'capture_in_scope': False, 'quad_physical_execution_validated': False,
                'short_context_fpga_win_claimed': False}
    (a.destination/'latency-package.json').write_text(json.dumps(manifest,indent=2)+'\n')
    shutil.copy2(ROOT/'LATENCY_RESULTS.md',a.destination/'LATENCY_RESULTS.md')
    print(json.dumps({'directory':str(a.destination),'sha256':manifest['archive_sha256'], 'files':len(hashes)}))

if __name__ == '__main__':
    main()
