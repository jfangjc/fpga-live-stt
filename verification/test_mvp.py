"""Host tests for bounds, physical error propagation and release integrity."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transcribe = load('mvp_transcribe', 'software/mvp/transcribe.py')
verify = load('mvp_verify', 'scripts/verify_mvp.py')


class MVPTests(unittest.TestCase):
    def test_frame_boundaries(self):
        for count in (0, 319, 40960, 160000):
            with self.assertRaises(ValueError):
                transcribe.validate_samples(count)
        self.assertEqual(transcribe.validate_samples(320), 3)
        self.assertEqual(transcribe.validate_samples(40959), 256)

    def test_manifest_rejects_tampering_and_missing_files(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder:
            root = Path(folder)
            payload = root/'payload'
            payload.write_text('original')
            manifest = root/'manifest.json'
            manifest.write_text(json.dumps({'release': 'kv260-asr-mvp-1.0',
                'files_sha256': {'payload': verify.digest(payload)}}))
            with patch.object(verify, 'ROOT', root):
                self.assertEqual(verify.verify_manifest(manifest), 1)
                payload.write_text('changed')
                with self.assertRaises(ValueError):
                    verify.verify_manifest(manifest)
                payload.unlink()
                with self.assertRaises(FileNotFoundError):
                    verify.verify_manifest(manifest)

    def test_manifest_rejects_escape(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder:
            root = Path(folder)
            manifest = root/'manifest.json'
            manifest.write_text(json.dumps({'release': 'kv260-asr-mvp-1.0',
                'files_sha256': {'../outside': '0'*64}}))
            with patch.object(verify, 'ROOT', root), self.assertRaises(ValueError):
                verify.verify_manifest(manifest)

    def fake_runtime(self, error=None, loads=256, ioctls=48):
        class Timer:
            def __init__(self, items):
                pass

            def call(self, runner, audio, kind):
                if error:
                    raise error
                return {'text': 'test', 'counters': {'loads': loads, 'ioctls': ioctls}}, None
        runtime = types.ModuleType('branch512_ab166_vf_benchmark')
        runtime.AudioTimer = Timer
        runtime.artifacts = lambda: {'boundary_library': 'boundary', 'library': 'physical'}
        runtime.bindings = lambda items: {}
        runtime.choose = lambda *args: 'physical_graph'
        runtime.configure = lambda core: None
        runtime.make_session = lambda *args: object()
        runtime.read_audio = lambda path: [0.0]*8000
        return runtime

    def run_fake(self, runtime):
        with patch.dict(sys.modules, {'branch512_ab166_vf_benchmark': runtime}), \
             patch.object(sys, 'argv', ['transcribe.py', 'clip.wav']), \
             patch.object(transcribe.os, 'sched_getaffinity', return_value={0, 1}, create=True), \
             patch.object(transcribe.os, 'sched_setaffinity', create=True) as affinity, \
             contextlib.redirect_stdout(io.StringIO()):
            try:
                transcribe.main()
            finally:
                self.assertEqual(affinity.call_args.args, (0, {0, 1}))

    def test_physical_failure_is_not_hidden(self):
        with self.assertRaisesRegex(RuntimeError, 'DMA failed'):
            self.run_fake(self.fake_runtime(RuntimeError('DMA failed')))

    def test_incorrect_physical_work_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Physical work'):
            self.run_fake(self.fake_runtime(loads=0))

    def test_success_restores_cpu_affinity(self):
        self.run_fake(self.fake_runtime())

    def test_cold_contract_matches_physical_first_inference(self):
        report = json.loads((ROOT/'reports/fused/branch512_ab166_vf_latency_confirmation.json').read_text())
        for context in report['contexts']:
            counters = context['first_fpga_inference']['counters']
            self.run_fake(self.fake_runtime(loads=counters['loads'], ioctls=counters['ioctls']))

    def test_warm_counters_do_not_satisfy_cold_registration(self):
        with self.assertRaisesRegex(RuntimeError, 'Physical work'):
            self.run_fake(self.fake_runtime(ioctls=24))


if __name__ == '__main__':
    unittest.main()
