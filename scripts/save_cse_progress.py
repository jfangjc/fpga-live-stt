"""Save a validated CSE latency overlay while preserving previous snapshots."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--destination', type=Path, required=True)
    ap.add_argument('--base', type=Path, required=True)
    a = ap.parse_args()
    if a.destination.exists():
        raise ValueError('Use a new destination; previous snapshots are immutable')
    base = read(ROOT / 'reports/fused/bulk_six_package.json')
    assert sha(a.base) == base['sha256']
    proofs = [ROOT / 'reports/fused/context_cse_confirmation100.json',
              ROOT / 'reports/fused/context_cse_short_confirmation100.json']
    for path in proofs:
        proof = read(path)
        assert proof['complete'] and proof['hardware_execution'] and proof['runs'] == 100
        assert sha(path.with_suffix('.onnx')) == proof['fpga_graph_sha256']
        assert sha(ROOT / 'research/fused/cpu-int8-cse.onnx') == proof['cpu_model_sha256']
        for key, rel in [('library_sha256', 'software/ort_fpga_bulk/libort_fpga.so'),
                         ('firmware_sha256', 'deployment/asr-v3-bulk/asr-v3-bulk.bit.bin')]:
            assert sha(ROOT / rel) == proof[key] == base['files'][rel]
        assert all(c['physical_oracle_bit_parity'] and c['old_new_cpu_bit_parity'] and
                   c['old_new_fpga_bit_parity'] for c in proof['contexts'])
    long = read(proofs[0])['contexts'][0]
    assert long['mean_saving_95ci_seconds'][0] > 0 and long['fpga_p50'] < long['cpu_p50']
    assert long['fpga_p95'] < long['cpu_p95']
    arm = read(ROOT / 'reports/fused/cse_arm_validation.json')
    physical = read(ROOT / 'reports/fused/cse_physical_validation.json')
    assert arm['complete'] and arm['all_logits_bit_exact']
    assert physical['complete'] and physical['wer_degradation_percentage_points'] <= 1
    smoke = read(ROOT / 'reports/fused/cse_resident_smoke.json')
    assert smoke['complete'] and smoke['caller_affinity_restored']
    assert smoke['resident_source_sha256'] == sha(ROOT / 'software/latency/resident.py')
    for call in smoke['results']['fpga']['calls']:
        assert call['fpga_counters']['physical_calls'] == len(physical['nodes'])
        assert call['fpga_counters']['oracle_calls'] == 0
    files = list((ROOT / 'software/latency').glob('*.py'))
    files += [ROOT / 'software/latency/README.md', ROOT / 'CSE_RESULTS.md', ROOT / 'LATENCY_RESULTS.md',
              ROOT / 'LIVE_PLAN.md', ROOT / 'RESULTS_V3.md', ROOT / 'PLAN_V3.md', Path(__file__).resolve(),
              ROOT / 'scripts/update_cse_results.py']
    files += list((ROOT / 'scripts').glob('run_cse*.sh'))
    files += list((ROOT / 'reports/fused').glob('*cse*.json'))
    files += [p.with_suffix('.onnx') for p in proofs]
    files += [ROOT / 'research/fused/cpu-int8-cse.onnx', ROOT / 'research/fused/cpu-int8-cse.json',
              ROOT / 'build/quad_system/Prototype_v3_quad.runs/impl_1/runme.log']
    hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(set(files))}
    a.destination.mkdir(parents=True)
    archive = a.destination / 'cse-latency-progress.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in hashes:
            z.write(ROOT / rel, rel)
            target = a.destination / 'project' / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, target)
    with zipfile.ZipFile(archive) as z:
        for rel, digest in hashes.items():
            assert hashlib.sha256(z.read(rel)).hexdigest() == digest == sha(a.destination / 'project' / rel)
    manifest = {'archive': archive.name, 'archive_sha256': sha(archive), 'files': hashes,
                'base_archive': str(a.base), 'base_sha256': base['sha256'],
                'instructions': 'Extract the verified six-operator base, then this overlay into the same project root.',
                'hardware': 'Verified 512-MAC 100-MHz bulk engine; six physical operators',
                'quad_status': 'Rejected: route_design failed with 1288 node overlaps; no deployment',
                'capture_in_scope': False, 'representative_corpus_qualified': False,
                'long_context_cpu_fpga_p50_seconds': [long['cpu_p50'], long['fpga_p50']]}
    (a.destination / 'cse-package.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    shutil.copy2(ROOT / 'CSE_RESULTS.md', a.destination / 'CSE_RESULTS.md')
    print(json.dumps({'directory': str(a.destination), 'sha256': manifest['archive_sha256'], 'files': len(hashes)}))


if __name__ == '__main__':
    main()
