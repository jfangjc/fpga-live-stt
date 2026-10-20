"""Clean-release KV260 test orchestration; credentials come from the environment."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HOST = 'ubuntu@192.168.1.111'
REMOTE = '/home/ubuntu/kv260-asr-mvp-clean-20261015'
KEY = 'SHA256:LKipAYiol8maTkeoe4VDOwZRuJLRLhyp1Nd7iSMk+1I'


def ssh(command, sudo=False):
    password = os.environ['ASR_KV260_PASSWORD']
    if sudo:
        command = 'sudo -S -p "" sh -c ' + shlex.quote(command)
    result = subprocess.run(['C:/Program Files/PuTTY/plink.exe', '-batch', '-hostkey', KEY,
        '-pw', password, HOST, command], input=password+'\n' if sudo else None,
        text=True, capture_output=True)
    print(result.stdout, end='')
    print(result.stderr, end='')
    if result.returncode:
        raise RuntimeError('Board command failed with exit code '+str(result.returncode))
    return result.stdout


def upload(source, destination):
    password = os.environ['ASR_KV260_PASSWORD']
    result = subprocess.run(['C:/Program Files/PuTTY/pscp.exe', '-batch', '-q', '-hostkey', KEY,
        '-pw', password, str(source), HOST+':'+destination], capture_output=True, text=True)
    if result.returncode:
        print(result.stderr)
        raise RuntimeError('Upload failed')


def download(pattern):
    password = os.environ['ASR_KV260_PASSWORD']
    result = subprocess.run(['C:/Program Files/PuTTY/pscp.exe', '-batch', '-q', '-hostkey', KEY,
        '-pw', password, HOST+':'+REMOTE+'/reports/mvp/'+pattern, str(ROOT/'reports/mvp')],
        capture_output=True, text=True)
    if result.returncode:
        print(result.stderr)
        raise RuntimeError('Evidence download failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'upload', 'upload-runtime', 'setup', 'install', 'inputs', 'smoke', 'reject', 'benchmark', 'collect'))
    args = parser.parse_args()
    if args.action == 'inspect':
        output = ssh('uname -a; python3 --version; df -h /home/ubuntu; '
            'xmutil listapps; cat /sys/class/fpga_manager/fpga0/state; '
            'cat /sys/module/qn_tile/parameters/bulk_protocol; '
            'cat /sys/bus/platform/devices/asr-v3-bulk-clock/set_rate; '
            'ps -eo pid,comm | grep -E "python|xmutil" || true; '
            'test ! -e '+REMOTE)
        (ROOT/'reports/mvp/clean_board_inspection.txt').write_text(output)
    elif args.action in ('upload', 'upload-runtime'):
        if args.action == 'upload':
            ssh('mkdir '+REMOTE)
            archive = 'kv260-asr-mvp-1.0.1.zip'
            checksum = 'SHA256SUMS.txt'
        else:
            ssh('test ! -e '+REMOTE+'/.venv && test ! -e '+REMOTE+'/software && '
                'if test -f '+REMOTE+'/release.zip; then mv '+REMOTE+'/release.zip '+REMOTE+'/handoff.partial; fi')
            archive = 'kv260-asr-mvp-1.0.1-runtime.zip'
            checksum = 'RUNTIME_SHA256SUMS.txt'
        upload(ROOT/'release'/archive, REMOTE+'/release.zip')
        upload(ROOT/'release'/checksum, REMOTE+'/SHA256SUMS.txt')
        ssh('cd '+REMOTE+' && python3 -c '+shlex.quote(
            "import hashlib,pathlib,zipfile; p=pathlib.Path('release.zip'); "
            "expected=pathlib.Path('SHA256SUMS.txt').read_text().split()[0]; "
            "assert hashlib.sha256(p.read_bytes()).hexdigest()==expected; "
            "zipfile.ZipFile(p).extractall('.'); print('PASS: clean archive hash and extraction')"))
    elif args.action == 'setup':
        ssh('cd '+REMOTE+' && mkdir -p reports/mvp && python3 -m venv .venv && '
            '.venv/bin/python -m pip install -r software/requirements-runtime.txt > reports/mvp/clean_install.log 2>&1 && '
            '.venv/bin/python -m pip freeze > reports/mvp/clean_pip_freeze.txt && '
            '.venv/bin/python scripts/verify_mvp.py --manifest release/MVP_MANIFEST.json && '
            '.venv/bin/python software/mvp/transcribe.py --help')
    elif args.action == 'install':
        ssh('set -eu; cd '+REMOTE+'; '
            'test "$(cat /sys/module/qn_tile/parameters/bulk_protocol)" = 1; '
            'mkdir preserved-firmware; '
            'mv /lib/firmware/xilinx/asr-v3-branch512-ab166 preserved-firmware/asr-v3-branch512-ab166; '
            'if ! .venv/bin/python scripts/install_branch512_ab166_firmware.py; then '
            'mv preserved-firmware/asr-v3-branch512-ab166 /lib/firmware/xilinx/asr-v3-branch512-ab166; exit 1; fi; '
            'echo "PASS: branch app freshly installed from clean release; prior app preserved"', sudo=True)
    elif args.action == 'inputs':
        ssh('mkdir -p '+REMOTE+'/test-inputs '+REMOTE+'/research/eval/user-recording')
        for path in (ROOT/'reports/mvp/test-audio').glob('*.wav'):
            upload(path, REMOTE+'/test-inputs/'+path.name)
        upload(ROOT/'research/eval/user-recording/speech.wav', REMOTE+'/research/eval/user-recording/speech.wav')
    elif args.action == 'smoke':
        for label in ('05', '10', '25'):
            ssh('cd '+REMOTE+' && sh scripts/run_mvp_board.sh software/mvp/transcribe.py '
                'test-inputs/speech_'+label+'.wav --out reports/mvp/clean_transcript_'+label+'.json '
                '> reports/mvp/clean_transcript_'+label+'.log 2>&1', sudo=True)
            ssh('cd '+REMOTE+' && .venv/bin/python -c '+shlex.quote(
                "import json; p=json.load(open('reports/mvp/clean_transcript_"+label+".json')); "
                "print(json.dumps({k:p[k] for k in ('audio_seconds','text','seconds','initialization_seconds','counters','hardware_execution')}))"))
    elif args.action == 'benchmark':
        ssh('cd '+REMOTE+' && sh scripts/run_mvp_board.sh software/latency/confirm_branch512_ab166_vf_latency.py '
            '--policy reports/fused/branch512_ab166_vf_latency_policy.json --runs 300 '
            '--out reports/mvp/clean_board_confirmation.json > reports/mvp/clean_board_confirmation.log 2>&1', sudo=True)
        # The deployment bundle excludes large archived physical graph files.
        # Audit downloaded new measurements against the full host evidence set.
        download('clean_board_confirmation.json')
        subprocess.run([sys.executable, 'scripts/audit_branch512_ab166_combined.py', '--variant', 'vf',
            '--report', 'reports/mvp/clean_board_confirmation.json',
            '--out', 'reports/mvp/clean_board_acceptance.json'], cwd=ROOT, check=True)
    elif args.action == 'reject':
        ssh('cd '+REMOTE+'; set +e; sh scripts/run_mvp_board.sh software/mvp/transcribe.py '
            'test-inputs/overlimit.wav > reports/mvp/clean_overlimit.log 2>&1; status=$?; '
            'echo "$status" > reports/mvp/clean_overlimit_exit.txt; test "$status" = 1 && '
            'grep -q "Expected 0.02 <= duration" reports/mvp/clean_overlimit.log && '
            'grep -q "PASS: compatible bulk image, loaded module, clock, device and IRQ masks" '
            'reports/mvp/clean_overlimit.log && echo "PASS: oversized input rejected and bulk restored"', sudo=True)
    elif args.action == 'collect':
        download('clean_*')
        download('bulk_*.json')


if __name__ == '__main__':
    main()
