"""Opt-in checkpoint parity: set MOONSHINE_TEST_WAV to a mono 16 kHz clip."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'software'))


@unittest.skipUnless(os.environ.get('MOONSHINE_TEST_WAV'), 'Set MOONSHINE_TEST_WAV for checkpoint validation')
class CheckpointTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('MOONSHINE_TEST_ENCODER'), 'Set MOONSHINE_TEST_ENCODER for native encoder validation')
    def test_native_float_encoder_preserves_chunked_memory(self):
        import numpy as np
        import soundfile as sf
        import torch
        from moonshine.model import load
        from moonshine.ort_encoder import Runtime
        from moonshine.streaming import Stream
        model, processor, metadata = load(os.environ.get('MOONSHINE_TEST_SIZE', 'small'), threads=2)
        runtime = Runtime(os.environ['MOONSHINE_TEST_ENCODER'], metadata, precision='float')
        reference, actual = Stream(model, processor), Stream(model, processor, encoder_runtime=runtime)
        audio, _ = sf.read(os.environ['MOONSHINE_TEST_WAV'], dtype='float32')
        # Odd chunk sizes exercise frame tails, convolution history and stride
        # phase; EOF releases the encoder's outstanding lookahead at every layer.
        for offset in range(0, len(audio), 7919):
            chunk = audio[offset:offset+7919]
            reference.push(chunk, decode=False)
            actual.push(chunk, decode=False)
        reference.push(np.empty(0), final=True, decode=False)
        actual.push(np.empty(0), final=True, decode=False)
        torch.testing.assert_close(torch.cat(actual.memory, dim=1), torch.cat(reference.memory, dim=1),
                                   rtol=3e-4, atol=3e-5)

    @unittest.skipUnless(os.environ.get('MOONSHINE_TEST_DECODER'), 'Set MOONSHINE_TEST_DECODER for native decoder validation')
    def test_native_float_decoder_preserves_every_update(self):
        import soundfile as sf
        from moonshine.model import load
        from moonshine.ort_decoder import Runtime
        from moonshine.streaming import Stream
        model, processor, meta = load(os.environ.get('MOONSHINE_TEST_SIZE', 'tiny'), threads=2)
        native = Runtime(os.environ['MOONSHINE_TEST_DECODER'], meta, precision='float')
        audio, _ = sf.read(os.environ['MOONSHINE_TEST_WAV'], dtype='float32')
        reference, actual = Stream(model, processor), Stream(model, processor, decoder_runtime=native)
        for offset in range(0, len(audio), 8000):
            chunk = audio[offset:offset+8000]
            self.assertEqual(actual.push(chunk)['tokens'], reference.push(chunk)['tokens'])
        self.assertEqual(actual.finish()['tokens'], reference.finish()['tokens'])

    def test_streaming_matches_pinned_reference(self):
        import numpy as np
        import soundfile as sf
        import torch
        from moonshine.model import load
        from moonshine.streaming import Stream
        audio, rate = sf.read(os.environ['MOONSHINE_TEST_WAV'], dtype='float32')
        self.assertEqual(rate, 16000)
        self.assertEqual(audio.ndim, 1)
        model, processor, _ = load(os.environ.get('MOONSHINE_TEST_SIZE', 'small'), threads=4)
        with torch.inference_mode():
            stream = Stream(model, processor)
            for offset in range(0, len(audio), 7919):
                stream.push(audio[offset:offset+7919])
            result = stream.finish()
            # Stream's explicit EOF contract treats a zero-padded tail as a full frame.
            framed = np.pad(audio, (0, (-len(audio)) % model.model.encoder.embedder.frame_len))
            inputs = processor(framed, sampling_rate=16000, return_tensors='pt')
            reference = model.model.encoder(**inputs).last_hidden_state
            torch.testing.assert_close(torch.cat(stream.memory, dim=1), reference, rtol=2e-4, atol=2e-5)
            generated = model.generate(**inputs, do_sample=False, max_new_tokens=stream.max_tokens)
            self.assertEqual(result['tokens'], generated[0].tolist())


if __name__ == '__main__':
    unittest.main()
