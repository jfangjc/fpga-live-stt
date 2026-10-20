"""Claim-integrity checks for model identity and physical execution evidence."""
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from benchmark import check_model, run
from evaluate_report import errors, words


class ClaimIntegrity(unittest.TestCase):
    def test_small_identity_and_wrong_heads(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            path = Path(root)/'model.bin'
            header = [0x67676d6c,51865,1500,768,12,12,448,768,12,12,80,1]
            path.write_bytes(struct.pack('<12i',*header))
            self.assertEqual(check_model(path),'openai/whisper-small')
            header[4] = 8
            path.write_bytes(struct.pack('<12i',*header))
            with self.assertRaises(ValueError):
                check_model(path)

    def test_turbo_identity_and_wrong_heads(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            path = Path(root)/'model.bin'
            header = [0x67676d6c,51866,1500,1280,20,32,448,1280,20,4,128,1]
            path.write_bytes(struct.pack('<12i',*header))
            self.assertEqual(check_model(path),'openai/whisper-large-v3-turbo')
            header[4] = 19
            path.write_bytes(struct.pack('<12i',*header))
            with self.assertRaises(ValueError):
                check_model(path)

    def test_rejects_english_only_model(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            path = Path(root)/'model.bin'
            header = [0x67676d6c,51865,1500,512,8,6,448,512,8,6,80,1]
            path.write_bytes(struct.pack('<12i',*header))
            check_model(path)
            header[1] = 51864
            path.write_bytes(struct.pack('<12i',*header))
            with self.assertRaises(ValueError):
                check_model(path)

    def test_rejects_cpu_fallback_as_physical(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            path = Path(root)/'placeholder'
            for stats in ['', 'KV260_STATS calls=0 seconds=0 ioctls=0 loads=0 runs=0']:
                result = subprocess.CompletedProcess([],0,'hello',stats)
                with patch('benchmark.subprocess.run',return_value=result):
                    with self.assertRaisesRegex(RuntimeError,'physical|Physical'):
                        run(path,path,path,4,True,Path(root)/'run.log')

    def test_propagates_device_failure(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            path = Path(root)/'placeholder'
            result = subprocess.CompletedProcess([],1,'','DMA failure')
            with patch('benchmark.subprocess.run',return_value=result):
                with self.assertRaisesRegex(RuntimeError,'exited 1'):
                    run(path,path,path,4,True,Path(root)/'run.log')

    def test_attention_requires_attention_counter(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            path = Path(root)/'placeholder'
            result = subprocess.CompletedProcess([],0,'hello',
                'KV260_STATS calls=48 seconds=1 ioctls=60 loads=60 runs=5640 attention_calls=0')
            with patch('benchmark.subprocess.run',return_value=result):
                with self.assertRaisesRegex(RuntimeError,'attention execution'):
                    run(path,path,path,4,True,Path(root)/'run.log',fpga_attention=True)

    def test_unfused_attention_is_explicit(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            path = Path(root)/'placeholder'
            result = subprocess.CompletedProcess([],0,'hello',
                'KV260_STATS calls=60 seconds=1 ioctls=300 loads=252 runs=23688 attention_calls=12')
            with patch('benchmark.subprocess.run',return_value=result) as launch:
                row = run(path,path,path,4,True,Path(root)/'run.log',fpga_attention=True)
            self.assertIn('-nfa',launch.call_args.args[0])
            self.assertNotIn('-fa',launch.call_args.args[0])
            self.assertFalse(row['flash_attention'])

    def test_corpus_word_errors(self):
        self.assertEqual(errors(words('One two three'),words('one four three five')),2)
        self.assertEqual(errors(words("Don't stop."),words("don't stop")),0)


if __name__ == '__main__':
    unittest.main()
