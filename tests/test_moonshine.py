"""Arithmetic tiling and chunk-boundary conformance for Moonshine."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'software'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from moonshine.matrix import PackedWeights, Projection, quantize_input, quantize_rows
from benchmark_moonshine import compare
from benchmark_moonshine_durations import qualify


class MatrixTests(unittest.TestCase):
    def test_prepacked_weights_follow_bulk_wire_layout(self):
        weights = np.array([[1, -2, 3], [4, -5, 6]], dtype=np.int8)
        packet = PackedWeights(weights).packet
        expected = np.zeros(64, dtype=np.uint8)
        expected[16:18] = [1, 4]
        expected[32:34] = [254, 251]
        expected[48:50] = [3, 6]
        np.testing.assert_array_equal(packet, expected)
        rng = np.random.default_rng(91)
        weights = rng.integers(-127, 128, (31, 71), dtype=np.int8)
        packet = PackedWeights(weights).packet.view(np.int8)
        for o in range(32):
            for k in range(71):
                self.assertEqual(packet[16+((o//16)*71+k)*16+o%16], weights[o, k] if o < 31 else 0)
        for invalid in (np.zeros((2, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.int8),
                        np.zeros((1025, 3), dtype=np.int8)):
            with self.assertRaises(ValueError): PackedWeights(invalid)

    def test_duration_gate_requires_complete_physical_runs(self):
        import copy
        events = [{'tokens': [1, 3], 'final': False, 'token_limit_reached': True},
                  {'tokens': [1, 3, 2], 'final': True, 'token_limit_reached': False}]
        case = {'audio_seconds': 2.5, 'oracle': {'runs': [{'events': events}]},
                'fpga': {'runs': [{'run': 0, 'seconds': 1.2, 'events': copy.deepcopy(events), 'physical': {'runs': 12, 'loads': 12}}]}}
        self.assertTrue(qualify(case)['realtime_execution_met'])
        for field, value in (('seconds', 2.6), ('physical', {'runs': 0}), ('physical', {'runs': 12, 'loads': 0})):
            bad = copy.deepcopy(case)
            bad['fpga']['runs'][0][field] = value
            self.assertFalse(qualify(bad)['realtime_execution_met'])
        bad = copy.deepcopy(case)
        bad['fpga']['runs'][0]['events'][-1]['token_limit_reached'] = True
        self.assertFalse(qualify(bad)['realtime_execution_met'])
        bad = copy.deepcopy(case)
        bad['fpga']['runs'][0]['events'][0]['tokens'] = [1, 4]
        self.assertFalse(qualify(bad)['realtime_execution_met'])

    def test_tiling_preserves_whole_matrix_scales(self):
        rng = np.random.default_rng(43)
        w = rng.normal(size=(37, 71)).astype(np.float32)
        x = rng.normal(size=(2, 19, 71)).astype(np.float32)
        bias = rng.normal(size=37).astype(np.float32)
        tiled = Projection(w, bias, tile=16)(x)
        whole = Projection(w, bias, tile=128)(x)
        np.testing.assert_array_equal(tiled, whole)

    def test_fpga_tile_route_matches_oracle(self):
        class Device:
            def __init__(self): self.calls = 0
            def multiply(self, w, x):
                self.calls += 1
                return w.astype(np.int32) @ x.astype(np.int32)
        rng = np.random.default_rng(7)
        w = rng.normal(size=(620, 2480)).astype(np.float32)
        x = rng.normal(size=(1, 3, 2480)).astype(np.float32)
        device = Device()
        actual = Projection(w, device=device)(x)
        np.testing.assert_array_equal(actual, Projection(w)(x))
        self.assertEqual(device.calls, 3)

    def test_zero_and_nearest_even(self):
        q, scale = quantize_input(np.array([.5, 1.5, 2.5, 127, -.5, -1.5], dtype=np.float32))
        np.testing.assert_array_equal(q, [0, 2, 2, 127, 0, -2])
        self.assertEqual(scale, 1)
        q, scales = quantize_rows(np.zeros((2, 7)))
        self.assertFalse(q.any())
        np.testing.assert_array_equal(scales, np.ones(2))
        np.testing.assert_array_equal(Projection(np.zeros((2, 7)), [1, 2])(np.zeros((3, 7))), [[1, 2]]*3)

    def test_reject_invalid_inputs(self):
        for value in (np.full((2, 3), np.nan), np.ones((0, 3)), np.ones(3)):
            with self.assertRaises(ValueError): Projection(value)
        with self.assertRaises(ValueError): Projection(np.ones((2, 3)))(np.ones((1, 4)))
        with self.assertRaises(ValueError): quantize_input(np.array([np.inf]))

    def test_accumulation_crosses_int32_boundary_without_overflow(self):
        # At this boundary the full sum exceeds INT32 even though each physical
        # K tile fits. All-one float inputs quantize to the maximum INT8 value.
        boundary = np.iinfo(np.int32).max // (127*127)
        for k in (boundary, boundary+1):
            projection = Projection(np.ones((1, k), np.float32))
            actual = projection(np.ones((1, k), np.float32))
            scale = np.float32(1)/np.float32(127)
            expected = np.float32(k*127*127)*np.float32(scale*scale)
            np.testing.assert_array_equal(actual, [[expected]])

    def test_projection_scratch_reuse_preserves_rounding_and_bias(self):
        rng = np.random.default_rng(271)
        for shape in ((3, 37), (17, 1031)):
            weights = rng.normal(size=shape).astype(np.float32)
            bias = rng.normal(size=shape[0]).astype(np.float32)
            x = rng.normal(size=(2, 7, shape[1])).astype(np.float32)
            p = Projection(weights, bias)
            qx, sx = quantize_input(x.reshape(-1, shape[1]).T)
            total = p.weights.astype(np.int64) @ qx.astype(np.int64)
            expected = total.astype(np.float32)*(p.scales[:, None]*sx)+bias[:, None]
            np.testing.assert_array_equal(p(x), expected.T.reshape(2, 7, shape[0]))

    def test_hardware_failure_propagates(self):
        class Broken:
            def multiply(self, w, x): raise OSError('DMA failure')
        with self.assertRaises(OSError): Projection(np.ones((2, 3)), device=Broken())(np.ones((1, 3)))

    def test_speedup_gate_uses_fastest_cpu_and_requires_physical_parity(self):
        import copy
        base = {'audio_sha256': 'a', 'revision': 'b', 'size': 'small', 'chunk_ms': 500,
                'final_only': False, 'max_tokens': 256, 'sample_count': 16000,
                'draft_reuse': True,
                'runtime_sources_sha256': 'c', 'torch_version': 'test', 'transformers_version': 'test', 'platform': 'test',
                'scope': 'encoder', 'threads': 4, 'cpu_tail_int8': True,
                'runs': [{'events': [{'tokens': [1, 2]}], 'text': ''}]}
        cpu = dict(base, backend='cpu', p50_seconds=10.)
        fast = dict(base, backend='cpu-int8', p50_seconds=3.)
        oracle = dict(base, backend='oracle', p50_seconds=20.)
        fpga = dict(base, backend='fpga', p50_seconds=2., physical={'runs': 10})
        result = compare([cpu, fast], oracle, fpga)
        self.assertEqual(result['speedup'], 1.5)
        self.assertFalse(result['target_met'])
        bad = copy.deepcopy(fpga)
        bad['physical']['runs'] = 0
        with self.assertRaises(ValueError): compare([cpu], oracle, bad)
        bad = copy.deepcopy(fpga)
        bad['runs'][0]['events'][0]['tokens'] = [1, 3]
        self.assertFalse(compare([cpu], oracle, bad)['target_met'])
        bad = dict(fpga, audio_sha256='other')
        with self.assertRaises(ValueError): compare([cpu], oracle, bad)
        bad = dict(fpga, decoder_runtime={'engine': 'onnxruntime'})
        with self.assertRaises(ValueError): compare([cpu, fast], oracle, bad)
        bad = dict(fpga, encoder_runtime={'engine': 'onnxruntime'})
        with self.assertRaises(ValueError): compare([cpu, fast], oracle, bad)
        # Real-time timing is independent of the 2x CPU speedup and accuracy gates.
        realtime = dict(fpga, p50_seconds=.8, p95_seconds=.9)
        result = compare([cpu, fast], oracle, realtime)
        self.assertTrue(result['realtime_timing_met'])
        realtime['runs'] = copy.deepcopy(realtime['runs'])
        realtime['runs'][0]['total_processing_seconds'] = .95
        self.assertTrue(compare([cpu, fast], oracle, realtime)['realtime_execution_met'])
        realtime['runs'][0]['total_processing_seconds'] = 1.01
        self.assertFalse(compare([cpu, fast], oracle, realtime)['realtime_execution_met'])
        realtime['p95_seconds'] = 1.1
        self.assertFalse(compare([cpu, fast], oracle, realtime)['realtime_timing_met'])


try:
    import torch
    from transformers.models.moonshine_streaming.configuration_moonshine_streaming import MoonshineStreamingEncoderConfig
    from transformers.models.moonshine_streaming.modeling_moonshine_streaming import MoonshineStreamingEncoder
    HAVE_TORCH = True
except ImportError:
    HAVE_TORCH = False


@unittest.skipUnless(HAVE_TORCH, 'Install Moonshine runtime dependencies for streaming tests')
class StreamingTests(unittest.TestCase):
    def test_final_decoding_uses_full_utterance_budget(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from moonshine.streaming import Stream
        class Cache:
            def __init__(self, length): self.length = length
            def get_seq_length(self): return self.length
            def crop(self, count): self.length += count
        class Decoder:
            def predict(self, ids, cache=None):
                old = cache.length if cache else 0
                n = ids.shape[1]
                return [2 if i >= 6 else 3 for i in range(old, old+n)], Cache(old+n)
        runtime = SimpleNamespace(update=lambda memory: Decoder())
        model = SimpleNamespace(config=SimpleNamespace(decoder_start_token_id=1, eos_token_id=2,
            max_position_embeddings=4096), model=SimpleNamespace(encoder=SimpleNamespace(embedder=None)))
        processor = SimpleNamespace(decode=lambda tokens, **kwargs: str(tokens))
        stage = SimpleNamespace(push=lambda data, final=False: torch.zeros(1, 1, 4))
        with patch('moonshine.streaming.Frontend', return_value=stage), patch('moonshine.streaming.Encoder', return_value=stage):
            stream = Stream(model, processor, max_tokens=12, decoder_runtime=runtime)
            self.assertTrue(stream.push(np.zeros(8000))['token_limit_reached'])
            result = stream.finish()
            self.assertFalse(result['token_limit_reached'])
            self.assertEqual(result['tokens'][-1], 2)
            self.assertGreater(len(result['tokens'])-1, 4)

    def test_native_decoder_graph_matches_reference_with_cache(self):
        from transformers.models.moonshine_streaming.configuration_moonshine_streaming import MoonshineStreamingConfig
        from transformers.models.moonshine_streaming.modeling_moonshine_streaming import MoonshineStreamingForConditionalGeneration
        from moonshine.ort_decoder import MemoryGraph, StepGraph, Cache
        from moonshine.streaming import DecoderUpdate
        torch.manual_seed(55)
        config = MoonshineStreamingConfig(hidden_size=16, intermediate_size=32, head_dim=8,
            num_attention_heads=2, num_key_value_heads=2, num_hidden_layers=2, vocab_size=64,
            encoder_config={'hidden_size': 16, 'intermediate_size': 32, 'num_attention_heads': 2,
                'num_key_value_heads': 2, 'head_dim': 8, 'num_hidden_layers': 2,
                'sliding_windows': [[4, 0], [4, 0]]})
        config._attn_implementation = 'sdpa'
        model = MoonshineStreamingForConditionalGeneration(config).eval()
        with torch.inference_mode():
            memory = torch.randn(1, 11, 16)
            cross = MemoryGraph(model.model.decoder)(memory)
            reference = DecoderUpdate(model.model.decoder, memory)
            past = torch.empty(2, 1, 2, 0, 8)
            pk = pv = past
            cache = None
            for ids in (torch.tensor([[1, 7, 9]]), torch.tensor([[13]]), torch.tensor([[2, 3]])):
                old, n = pk.shape[3], ids.shape[1]
                positions = torch.arange(old, old+n)[None]
                mask = torch.where(torch.arange(old+n)[None] <= positions.T, 0., -float('inf'))[None, None]
                expected, cache = reference(ids, cache)
                actual, pk, pv = StepGraph(model)(ids, positions, mask, pk, pv, *cross)
                torch.testing.assert_close(actual, model.proj_out(expected), rtol=3e-5, atol=3e-6)
            native = Cache(pk.numpy(), pv.numpy())
            native.crop(-2); cache.crop(-2)
            self.assertEqual(native.get_seq_length(), cache.get_seq_length())
            np.testing.assert_allclose(native.keys[0], cache.self_attention_cache.layers[0].keys.numpy(), rtol=3e-5, atol=3e-6)
            with self.assertRaises(ValueError): native.crop(0)

    def test_convolution_lowering_matches_reference(self):
        from transformers.models.moonshine_streaming.modeling_moonshine_streaming import MoonshineStreamingCausalConv1d
        from moonshine.model import Convolution
        torch.manual_seed(15)
        conv = MoonshineStreamingCausalConv1d(16, 32, kernel_size=5, stride=2).eval()
        lowered = Convolution(conv).eval()
        x = torch.randn((1, 16, 79))
        mask = torch.ones((1, 79), dtype=torch.bool)
        mask[:, -7:] = False
        with torch.inference_mode():
            expected, em = conv(x, mask)
            actual, am = lowered(x, mask)
        torch.testing.assert_close(actual, expected, rtol=2e-5, atol=2e-6)
        torch.testing.assert_close(am, em)

    def test_chunked_frontend_and_encoder_match_reference(self):
        from moonshine.streaming import Frontend, Encoder
        torch.manual_seed(13)
        torch.set_num_threads(1)
        config = MoonshineStreamingEncoderConfig(hidden_size=16, intermediate_size=32,
            num_attention_heads=2, num_key_value_heads=2, head_dim=8,
            num_hidden_layers=3, sliding_windows=[[4, 3], [4, 0], [4, 2]])
        config._attn_implementation = 'eager'
        enc = MoonshineStreamingEncoder(config).eval()
        for length in (1, 79, 80, 321, 4097, 16000):
            waveform = torch.randn((1, length)) * .1
            with torch.inference_mode():
                frontend, encoder = Frontend(enc.embedder), Encoder(enc)
                chunks, features = [], []
                start = 0
                for size in [1, 78, 33, 511, 80, 79, 1024, 207, 4096, 10000]:
                    if start >= length: break
                    stop = min(start+size, length)
                    f = frontend.push(waveform[0, start:stop].numpy())
                    features.append(f)
                    chunks.append(encoder.push(f))
                    start = stop
                if start < length:
                    f = frontend.push(waveform[0, start:].numpy())
                    features.append(f); chunks.append(encoder.push(f))
                f = frontend.push(np.empty(0), final=True)
                features.append(f); chunks.append(encoder.push(f, final=True))
                padded = torch.nn.functional.pad(waveform, (0, (-length) % enc.embedder.frame_len))
                reference_features, _ = enc.embedder(padded)
                torch.testing.assert_close(torch.cat(features, dim=1), reference_features, rtol=2e-5, atol=2e-6)
                reference = enc(padded, attention_mask=torch.ones_like(padded, dtype=torch.long)).last_hidden_state
                torch.testing.assert_close(torch.cat(chunks, dim=1), reference, rtol=3e-5, atol=3e-6)
                for b, window in zip(encoder.buffers, config.sliding_windows):
                    self.assertLessEqual(b.shape[1], window[0] - 1 + max(0, window[1]-1))


if __name__ == '__main__':
    unittest.main()
