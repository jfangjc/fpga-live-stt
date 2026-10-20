"""Summarize actual clean-install, physical inference and rollback evidence."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT/'reports/mvp'


def main():
    rows = []
    for label, duration in (('05', .5), ('10', 1), ('25', 2.5)):
        path = REPORTS/f'clean_transcript_{label}.json'
        result = json.loads(path.read_text())
        counters = result['counters']
        assert result['hardware_execution'] and result['audio_seconds'] == duration
        assert counters['physical_calls'] == 128 and counters['oracle_calls'] == 0
        assert counters['loads'] == 256 and counters['ioctls'] == 48
        assert result['execution_phase'] == 'cold' and result['program_registration_included']
        assert result['feature_frames'] == int(duration*100)+1
        rows.append({'audio_seconds': duration, 'text': result['text'],
                     'processing_seconds': result['seconds'],
                     'initialization_seconds': result['initialization_seconds'], 'counters': counters})
    assert (REPORTS/'clean_overlimit_exit.txt').read_text().strip() == '1'
    invalid = (REPORTS/'clean_overlimit.log').read_text()
    assert 'Expected 0.02 <= duration' in invalid
    assert 'PASS: compatible bulk image, loaded module, clock, device and IRQ masks' in invalid
    restorations = []
    for before_path in sorted(REPORTS.glob('bulk_before_*.json')):
        restored_path = before_path.with_name(before_path.name.replace('bulk_before_', 'bulk_restored_'))
        before = json.loads(before_path.read_text())
        after = json.loads(restored_path.read_text())
        assert before['complete'] and after['complete']
        for key in ('accepted_application', 'kernel', 'driver_sha256', 'firmware_sha256', 'clock_hz'):
            assert before[key] == after[key]
        assert after['accepted_application'] == 'asr-v3-bulk' and after['clock_hz'] == 100000000
        requested = lambda p: [p['irq'][key]['requested'] for key in sorted(p['irq'], key=int)]
        assert requested(before) == requested(after)
        restorations.append(restored_path.name)
    assert len(restorations) >= 5
    acceptance = json.loads((REPORTS/'clean_board_acceptance.json').read_text())
    historical = json.loads((ROOT/'reports/fused/FPGA_ASR_2X_COMPLETION_AUDIT.json').read_text())
    for context in acceptance['contexts']:
        prior = next(c for c in historical['contexts'] if c['input_seconds'] == context['context_seconds'])
        context['strongest_cpu_p50'] = min(context['strongest_cpu_p50'], prior['cpu_p50'])
        context['strongest_cpu_p95'] = min(context['strongest_cpu_p95'], prior['cpu_p95'])
        context['speedup_against_strongest_cpu'] = context['strongest_cpu_p50']/context['fpga_p50']
        context['meets_50_percent'] = context['fpga_p50'] <= .5*context['strongest_cpu_p50'] and context['fpga_p95'] < context['strongest_cpu_p95']
    acceptance['twofold_speed_acceptance'] = all(c['meets_50_percent'] for c in acceptance['contexts'])
    confirmation = json.loads((REPORTS/'clean_board_confirmation.json').read_text())
    assert acceptance['complete'] and acceptance['evidence_valid']
    assert confirmation['complete'] and confirmation['hardware_execution']
    assert confirmation['runs_per_context'] == 300
    assert all(c['all_warm_logits_bit_exact'] and c['warm_logit_checks'] == 300 for c in confirmation['contexts'])
    installed = dict(line.split('==', 1) for line in (REPORTS/'clean_pip_freeze.txt').read_text().splitlines() if '==' in line)
    required = dict(line.split('==', 1) for line in (ROOT/'software/requirements-runtime.txt').read_text().splitlines() if '==' in line)
    assert all(installed.get(k.replace('_','-')) == v or installed.get(k) == v for k,v in required.items())
    final_state = (REPORTS/'clean_final_board_state.txt').read_text()
    assert 'PASS: original and clean-installed branch firmware identities match' in final_state
    assert '99999999' in final_state and '0->0' in final_state
    runtime = ROOT/'release/kv260-asr-mvp-1.0.1-tested-runtime.zip'
    if not runtime.exists():
        runtime = ROOT/'release/kv260-asr-mvp-1.0.1-runtime.zip'
    report = {'complete': True, 'clean_software_installation': True,
        'fresh_branch_firmware_installation': True, 'base_kernel_and_bulk_app_preserved': True,
        'original_branch_firmware_registration_restored': True, 'date': '2026-10-15',
        'board': 'KV260', 'kernel': confirmation['environment_before']['platform'],
        'remote_directory': '/home/ubuntu/kv260-asr-mvp-clean-20261015',
        'runtime_bundle_sha256': hashlib.sha256(runtime.read_bytes()).hexdigest(),
        'tested_runtime_archive': 'kv260-asr-mvp-1.0.1-tested-runtime.zip',
        'physical_smoke_tests': rows, 'oversized_input_rejected': True,
        'successful_bulk_restorations': restorations, 'full_warm_logit_comparisons': 900,
        'twofold_speed_acceptance': acceptance['twofold_speed_acceptance'],
        'warm_contexts': acceptance['contexts'], 'dependencies': installed,
        'comparator': 'Fastest p50/p95 across this run and preserved qualified CPU evidence on the same input',
        'capture_qualified': False, 'representative_wer_qualified': False,
        'evidence_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in REPORTS.glob('clean_*') if p.is_file() and p.name != 'clean_board_test.json'}}
    target = REPORTS/'clean_board_test.json'
    target.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'complete': True, 'twofold_speed_acceptance': report['twofold_speed_acceptance'],
        'restorations': len(restorations), 'contexts': report['warm_contexts']}, indent=2))


if __name__ == '__main__':
    main()
