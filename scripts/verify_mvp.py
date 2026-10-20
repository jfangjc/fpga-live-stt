"""Verify a release manifest or audit the preserved MVP evidence on a host."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def verify_manifest(path):
    data = json.loads(path.read_text())
    if data.get('release') not in ('kv260-asr-mvp-1.0', 'kv260-asr-mvp-1.0.1') or not data.get('files_sha256'):
        raise ValueError('Invalid MVP manifest')
    for name, expected in data['files_sha256'].items():
        target = (ROOT / name).resolve()
        if not target.is_relative_to(ROOT) or digest(target) != expected:
            raise ValueError('Release file missing or changed: ' + name)
    return len(data['files_sha256'])


def audit():
    if not __debug__:
        raise RuntimeError('Evidence scripts use assertions; do not run Python with -O')
    for command in (
        ['verification/test_mvp.py'],
        ['verification/test_mvp_runner.py'],
        ['scripts/check_branch512_ab_software.py'],
        ['software/latency/check_more_model_evidence.py'],
        ['scripts/audit_branch512_ab166_combined.py', '--variant', 'vf',
         '--out', 'reports/mvp/latency_acceptance.json'],
        ['scripts/final_completion_audit.py'],
    ):
        subprocess.run([sys.executable, *command], cwd=ROOT, check=True)
    proof = json.loads((ROOT / 'reports/fused/branch512_ab166_firmware_evidence.json').read_text())
    checked = set()

    def check_bindings(name):
        if name in checked:
            return
        checked.add(name)
        path = ROOT / name
        if path.suffix != '.json':
            return
        data = json.loads(path.read_text())
        for key in ('sources_sha256', 'sources_and_evidence_sha256'):
            for child, expected in data.get(key, {}).items():
                if digest(ROOT / child) != expected:
                    raise ValueError('Evidence binding changed: ' + child)
                check_bindings(child)

    check_bindings('reports/fused/branch512_ab166_firmware_evidence.json')
    directory = ROOT / 'deployment/asr-v3-branch512-ab166'
    for name, key in (('asr-v3-branch512-ab166.bit.bin', 'firmware_bin_sha256'),
                      ('asr-v3-branch512-ab166.dtbo', 'overlay_sha256'),
                      ('shell.json', 'shell_sha256')):
        if digest(directory / name) != proof[key]:
            raise ValueError('Firmware binding changed: ' + name)
    drc = (ROOT / 'reports/fused/branch512_ab166_system_drc.rpt').read_text().split('2. REPORT DETAILS')[0]
    if re.search(r'\|\s*(Error|Critical Warning)\s*\|', drc):
        raise ValueError('Routed DRC gate failed')
    if proof['setup_slack_ns'] < .001 or proof['hold_slack_ns'] < 0:
        raise ValueError('Routed timing gate failed')
    simulations = {}
    for name, marker in (
        ('ab_mac_conformance', 'PASS: 203980 old/new vendor DSP and model checks'),
        ('branch512_ab_fast_sim', 'PASS: 25 two-output residual branches'),
        ('branch512_ab_reset_sim', 'PASS: 6 full-pipeline reset/replay cases'),
        ('branch512_ab_payload_reset_sim', 'PASS: 2 full output-data buffer reset/replay cases'),
    ):
        path = ROOT / f'build/mvp_{name}/mvp_{name}.sim/sim_1/behav/xsim/simulate.log'
        text = path.read_text()
        if marker not in text or re.search(r'Fatal:|ERROR:|cannot be opened for reading', text):
            raise ValueError('Fresh simulation failed: ' + name)
        simulations[path.relative_to(ROOT).as_posix()] = digest(path)
    project_log = ROOT/'reports/mvp/project_check.log'
    if 'PASS: MVP project check completed' not in project_log.read_text():
        raise ValueError('Clean Vivado project check incomplete')
    frontend_path = ROOT/'reports/mvp/frontend_validation.json'
    frontend = json.loads(frontend_path.read_text())
    if not frontend['complete'] or not frontend['all_model_inputs_bit_exact']:
        raise ValueError('Fresh frontend equivalence check failed')
    if frontend['candidate_sha256'] != digest(ROOT/'software/latency/frontend_valid_frames.py'):
        raise ValueError('Fresh frontend source binding changed')
    result = {'complete': True, 'release': 'kv260-asr-mvp-1.0.1',
              'scope': 'Bounded WAV transcription on KV260; archived physical results re-audited',
              'fresh_physical_execution': False, 'fresh_rtl_simulation': True,
              'capture_qualified': False, 'representative_wer_qualified': False,
              'firmware_binding_files_checked': len(checked), 'fresh_simulations_sha256': simulations,
              'host_tests_passed': 13, 'fresh_project_check_sha256': digest(project_log),
              'fresh_frontend_validation_sha256': digest(frontend_path),
              'completion_audit_sha256': digest(ROOT / 'reports/fused/FPGA_ASR_2X_COMPLETION_AUDIT.json')}
    board_test = ROOT/'reports/mvp/clean_board_test.json'
    if board_test.is_file():
        physical = json.loads(board_test.read_text())
        if not physical['complete'] or physical['full_warm_logit_comparisons'] != 900:
            raise ValueError('Clean board qualification incomplete')
        result.update(clean_board_test_sha256=digest(board_test),
                      clean_board_functional_tests_passed=True,
                      clean_board_strict_twofold_speed_acceptance=physical['twofold_speed_acceptance'])
    (ROOT / 'reports/mvp/verification.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, help='Verify every packaged file; no hardware activation')
    args = parser.parse_args()
    if args.manifest:
        print('PASS: release files verified:', verify_manifest(args.manifest))
    else:
        (ROOT / 'reports/mvp').mkdir(parents=True, exist_ok=True)
        print(json.dumps(audit(), indent=2))


if __name__ == '__main__':
    main()
