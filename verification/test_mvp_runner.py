"""Exercise the real runner control flow with fake board commands and sysfs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which('bash') if os.name != 'nt' else 'C:/Program Files/Git/bin/bash.exe'


class RunnerTests(unittest.TestCase):
    def run_case(self, failure=''):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder:
            root = Path(folder)
            for name in ('scripts', '.venv/bin', 'bin', 'fake-sys/module/qn_tile',
                         'deployment/experimental-stream-branch',
                         'deployment/kernel-compat/test-kernel/bulk',
                         'fake-sys/bus/platform/devices/asr-v3-bulk-clock',
                         'fake-sys/bus/platform/devices/asr-v3-branch512-ab166-clock',
                         'fake-sys/class/fpga_manager/fpga0', 'fake-dev'):
                (root/name).mkdir(parents=True, exist_ok=True)
            for name in ('deployment/experimental-stream-branch/qn_tile.ko',
                         'deployment/kernel-compat/test-kernel/bulk/qn_tile.ko', 'fake-dev/qn-tile'):
                (root/name).touch()
            (root/'fake-sys/class/fpga_manager/fpga0/state').write_text('operating\n')
            source = (ROOT/'scripts/run_mvp_board.sh').read_text()
            source = source.replace('/sys/', '$root/fake-sys/').replace('test -c /dev/qn-tile', 'test -f "$root/fake-dev/qn-tile"')
            (root/'scripts/runner.sh').write_text(source, newline='\n')
            commands = {
                'id': 'echo 0', 'uname': 'echo test-kernel',
                'modinfo': 'if test "$FAILURE" = kernel; then echo wrong-kernel; else echo "test-kernel SMP"; fi',
                'xmutil': 'echo "xmutil $*" >> "$TEST_LOG"\nif test "$FAILURE" = activation && test "$*" = "loadapp asr-v3-branch512-ab166"; then exit 9; fi\nif test "$FAILURE" = restoration && test "$*" = "loadapp asr-v3-bulk"; then exit 8; fi',
                'rmmod': 'echo rmmod >> "$TEST_LOG"\nrmdir "$TEST_ROOT/fake-sys/module/qn_tile"',
                'insmod': 'echo "insmod $*" >> "$TEST_LOG"\nmkdir -p "$TEST_ROOT/fake-sys/module/qn_tile/parameters"\necho 1 > "$TEST_ROOT/fake-sys/module/qn_tile/parameters/residual_branch_protocol"',
            }
            # rmmod removes only the fake module marker; parameters need to be
            # removed for the subsequent rollback invocation in this fixture.
            commands['rmmod'] = 'echo rmmod >> "$TEST_LOG"\nif test -f "$TEST_ROOT/fake-sys/module/qn_tile/parameters/residual_branch_protocol"; then unlink "$TEST_ROOT/fake-sys/module/qn_tile/parameters/residual_branch_protocol"; rmdir "$TEST_ROOT/fake-sys/module/qn_tile/parameters"; fi\nrmdir "$TEST_ROOT/fake-sys/module/qn_tile"'
            for name, body in commands.items():
                path = root/'bin'/name
                path.write_text('#!/bin/sh\n'+body+'\n', newline='\n')
                path.chmod(0o755)
            python = root/'.venv/bin/python'
            python.write_text('#!/bin/sh\necho "python $*" >> "$TEST_LOG"\nif test "$1" = -; then cat >/dev/null; fi\nif test "$1" = job.py && test "$FAILURE" = job; then exit 7; fi\n', newline='\n')
            python.chmod(0o755)
            log = root/'events.log'
            env = os.environ | {'TEST_LOG': log.as_posix(), 'TEST_ROOT': root.as_posix(), 'FAILURE': failure}
            prefix = 'export TEST_ROOT=$(cygpath -u "$TEST_ROOT"); ' if os.name == 'nt' else ''
            result = subprocess.run([BASH, '-c', prefix+'export PATH="$TEST_ROOT/bin:$PATH"; exec sh "$TEST_ROOT/scripts/runner.sh" job.py'],
                                    env=env, text=True, capture_output=True)
            events = (log.read_text() if log.exists() else '') + result.stderr
            clock = root/'fake-sys/bus/platform/devices/asr-v3-bulk-clock/set_rate'
            return result.returncode, events, clock.read_text().strip() if clock.exists() else None

    def test_success_restores_bulk(self):
        code, events, clock = self.run_case()
        self.assertEqual(code, 0, events)
        self.assertIn('loadapp asr-v3-bulk', events)
        self.assertIn('--out reports/mvp/bulk_restored_', events)
        self.assertEqual(clock, '100000000')

    def test_job_failure_restores_and_preserves_exit_status(self):
        code, events, clock = self.run_case('job')
        self.assertEqual(code, 7, events)
        self.assertIn('loadapp asr-v3-bulk', events)
        self.assertEqual(clock, '100000000')

    def test_activation_failure_restores_bulk(self):
        code, events, clock = self.run_case('activation')
        self.assertEqual(code, 9, events)
        self.assertIn('loadapp asr-v3-bulk', events)
        self.assertEqual(clock, '100000000')

    def test_kernel_mismatch_prevents_mutation(self):
        code, events, clock = self.run_case('kernel')
        self.assertNotEqual(code, 0)
        self.assertNotIn('rmmod', events)
        self.assertNotIn('xmutil', events)
        self.assertIsNone(clock)

    def test_restoration_failure_is_reported(self):
        code, events, clock = self.run_case('restoration')
        self.assertNotEqual(code, 0)
        self.assertNotIn('--out reports/mvp/bulk_restored_', events)


if __name__ == '__main__':
    unittest.main()
