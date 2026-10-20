"""Run a KV260 experiment and restore the previously active application.

For the inspected stock starter-kit state only: refuses an existing qn_tile
module, ambiguous applications, wrong firmware or a mismatched kernel module.
Invoke with sudo; credentials are never read or stored by this program.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import os
import signal
import time
import fcntl

BULK_SHA = 'b8381da2d15c7b60dc1bb97aa27534897c7977e20ab03e8894bd91e5c345c32e'


def execute(*command):
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)


def active_app(allow_none=False):
    output = execute('xmutil', 'listapps')
    apps = [line.split()[-1] for line in output.splitlines() if re.search(r'\d+->\d+', line)]
    if not apps and allow_none:
        return None
    if len(apps) != 1:
        raise RuntimeError('Expected exactly one active application: '+output)
    return apps[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--release', required=True, type=Path)
    ap.add_argument('--expected-app', required=True)
    ap.add_argument('--evidence', required=True, type=Path)
    ap.add_argument('command', nargs=argparse.REMAINDER)
    a = ap.parse_args()
    if os.geteuid() != 0:
        ap.error('Run with sudo')
    if a.command[:1] == ['--']:
        a.command = a.command[1:]
    if not a.command:
        ap.error('Command required after --')
    lock_handle = open('/run/lock/kv260-whisper.lock','a')
    try:
        fcntl.flock(lock_handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Another supported Whisper hardware session owns the FPGA')
    a.evidence.parent.mkdir(parents=True, exist_ok=True)
    if a.evidence.exists():
        raise RuntimeError('Refusing to overwrite evidence')
    original = active_app()
    if original != a.expected_app or original != 'k26-starter-kits':
        raise RuntimeError('This wrapper requires the inspected stock starter-kit state')
    if Path('/sys/module/qn_tile').exists():
        raise RuntimeError('Existing qn_tile module; preserve its identity before using another session wrapper')
    module = a.release / 'deployment/kernel-compat' / platform.release() / 'bulk/qn_tile.ko'
    if execute('modinfo', '-F', 'vermagic', str(module)).split()[0] != platform.release():
        raise RuntimeError('Kernel module mismatch')
    firmware = Path('/lib/firmware/xilinx/asr-v3-bulk/asr-v3-bulk.bit.bin')
    actual = hashlib.sha256(firmware.read_bytes()).hexdigest()
    if actual != BULK_SHA:
        raise RuntimeError('Unexpected installed bulk firmware')
    record = {'original_app': original, 'original_qn_module': False, 'kernel': platform.release(),
              'firmware_sha256': actual, 'driver_sha256': hashlib.sha256(module.read_bytes()).hexdigest(),
              'command': a.command, 'restored': False}
    status = 1
    mutated = False
    session_start = time.perf_counter()
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'Interrupted by signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        # Mark before attempting unload so failures also enter restoration.
        mutated = True
        print(execute('xmutil', 'unloadapp'), flush=True)
        print(execute('xmutil', 'loadapp', 'asr-v3-bulk'), flush=True)
        clock = Path('/sys/bus/platform/devices/asr-v3-bulk-clock/set_rate')
        clock.write_text('100000000')
        execute('insmod', str(module))
        if Path('/sys/module/qn_tile/parameters/bulk_protocol').read_text().strip() != '1':
            raise RuntimeError('Bulk protocol unavailable')
        if not Path('/dev/qn-tile').is_char_device():
            raise RuntimeError('Missing DMA character device')
        record['clock_hz'] = int(clock.read_text())
        if abs(record['clock_hz'] - 100000000) > 1:
            raise RuntimeError('Unexpected PL clock')
        record['activation_seconds'] = time.perf_counter()-session_start
        command_start = time.perf_counter()
        child = subprocess.Popen(a.command,start_new_session=True)
        try:
            status = child.wait()
        except BaseException:
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid,signal.SIGKILL)
                    child.wait()
            raise
        finally:
            record['command_seconds'] = time.perf_counter()-command_start
        record['command_exit_code'] = status
    finally:
        restoration_start = time.perf_counter()
        try:
            if mutated:
                if Path('/sys/module/qn_tile').exists():
                    execute('rmmod', 'qn_tile')
                current = active_app(allow_none=True)
                if current != original:
                    if current is not None:
                        execute('xmutil', 'unloadapp')
                    execute('xmutil', 'loadapp', original)
                record['restored'] = (active_app() == original and
                    not Path('/sys/module/qn_tile').exists() and
                    Path('/sys/class/fpga_manager/fpga0/state').read_text().strip() == 'operating')
                if not record['restored']:
                    raise RuntimeError('FPGA state restoration verification failed')
        finally:
            record['restoration_seconds'] = time.perf_counter()-restoration_start
            record['session_seconds'] = time.perf_counter()-session_start
            a.evidence.write_text(json.dumps(record, indent=2)+'\n')
            lock_handle.close()
    raise SystemExit(status)


if __name__ == '__main__':
    main()
