"""Model adapters. Each one loads once in __init__ and exposes
transcribe(audio) -> str, where audio is mono float32 at 16 kHz.

All adapters run on the KV260's Cortex-A53 CPU (no DPU).
"""
import json
from pathlib import Path

import numpy as np

SR = 16000
HERE = Path(__file__).resolve().parent


class FasterWhisper:
    """OpenAI Whisper via CTranslate2 (int8), greedy decoding."""

    def __init__(self, size, threads):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=threads)

    def transcribe(self, audio):
        segments, _ = self.model.transcribe(
            audio,
            language="en",
            beam_size=1,
            without_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        # segments is a lazy generator: decoding happens while iterating.
        return " ".join(s.text.strip() for s in segments)


class MoonshineOnnx:
    """Useful Sensors Moonshine via ONNX Runtime."""

    def __init__(self, name, threads):
        from moonshine_onnx import MoonshineOnnxModel, load_tokenizer

        import onnxruntime as ort
        from moonshine_onnx.model import _get_onnx_weights
        # The package constructor does not accept thread settings. Reuse its
        # decoding implementation with explicitly configured CPU sessions.
        self.model = MoonshineOnnxModel.__new__(MoonshineOnnxModel)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        encoder, decoder = _get_onnx_weights(name.split('/')[-1], 'float')
        self.model.encoder = ort.InferenceSession(encoder, opts, providers=['CPUExecutionProvider'])
        self.model.decoder = ort.InferenceSession(decoder, opts, providers=['CPUExecutionProvider'])
        self.model.encoder_input_names = [x.name for x in self.model.encoder.get_inputs()]
        self.model.decoder_input_names = [x.name for x in self.model.decoder.get_inputs()]
        self.model.num_layers = 6
        self.model.num_key_value_heads = 8
        self.model.head_dim = 36
        self.model.decoder_start_token_id = 1
        self.model.eos_token_id = 2
        self.tokenizer = load_tokenizer()

    def transcribe(self, audio):
        tokens = self.model.generate(audio[np.newaxis, :].astype(np.float32))
        return self.tokenizer.decode_batch(tokens)[0]


class MoonshineStreaming:
    """Vendor streaming checkpoint evaluated with the benchmark's offline API."""

    def __init__(self, size, threads):
        from moonshine_voice import Transcriber, get_model_for_language, ModelArch

        arch = getattr(ModelArch, size.upper() + '_STREAMING')
        path, arch = get_model_for_language('en', arch)
        self.model = Transcriber(model_path=path, model_arch=arch)

    def transcribe(self, audio):
        result = self.model.transcribe_without_streaming(audio.tolist(), sample_rate=SR)
        return ' '.join(line.text for line in result.lines)


def _hz_to_mel(f):
    f = np.asanyarray(f, dtype=np.float64)
    f_sp = 200.0 / 3
    min_log_hz, logstep = 1000.0, np.log(6.4) / 27.0
    return np.where(
        f >= min_log_hz,
        min_log_hz / f_sp + np.log(np.maximum(f, min_log_hz) / min_log_hz) / logstep,
        f / f_sp,
    )


def _mel_to_hz(m):
    m = np.asanyarray(m, dtype=np.float64)
    f_sp = 200.0 / 3
    min_log_hz, logstep = 1000.0, np.log(6.4) / 27.0
    min_log_mel = min_log_hz / f_sp
    return np.where(m >= min_log_mel, min_log_hz * np.exp(logstep * (m - min_log_mel)), f_sp * m)


def _slaney_mel_filters(sr, n_fft, n_mels):
    """Same filterbank as librosa.filters.mel(norm='slaney', htk=False), which NeMo uses."""
    fft_freqs = np.linspace(0, sr / 2, n_fft // 2 + 1)
    mel_f = _mel_to_hz(np.linspace(_hz_to_mel(0), _hz_to_mel(sr / 2), n_mels + 2))
    fdiff = np.diff(mel_f)
    ramps = mel_f[:, None] - fft_freqs[None, :]
    lower = -ramps[:-2] / fdiff[:-1, None]
    upper = ramps[2:] / fdiff[1:, None]
    weights = np.maximum(0, np.minimum(lower, upper))
    weights *= (2.0 / (mel_f[2 : n_mels + 2] - mel_f[:n_mels]))[:, None]
    return weights.astype(np.float32)


class NemoCtcOnnx:
    """NVIDIA NeMo CTC model (QuartzNet / Citrinet) exported with export_nemo.py.

    The NeMo preprocessor is not part of the ONNX graph, so it is reimplemented
    here in numpy. Sanity check: QuartzNet15x5 should land around 4-6% WER on
    LibriSpeech test-clean. Much worse means the features don't match.
    """

    def __init__(self, name, threads):
        import onnxruntime as ort

        cfg = json.loads((HERE / "nemo" / f"{name}.json").read_text(encoding="utf-8"))
        self.vocab = cfg["vocab"]
        self.wordpiece = any(token.startswith('##') for token in self.vocab)
        self.blank = len(self.vocab)
        self.pad_to = cfg.get('pad_to', 16)
        self.win_length = int(cfg["window_size"] * SR)
        self.hop_length = int(cfg["window_stride"] * SR)
        self.n_fft = cfg["n_fft"] or 2 ** int(np.ceil(np.log2(self.win_length)))
        self.mel = _slaney_mel_filters(SR, self.n_fft, cfg["features"])
        pad = (self.n_fft - self.win_length) // 2
        window = np.zeros(self.n_fft, dtype=np.float32)
        window[pad : pad + self.win_length] = np.hanning(self.win_length)  # torch periodic=False
        self.window = window

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(
            str(HERE / "nemo" / f"{name}.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        self.input_names = [i.name for i in self.sess.get_inputs()]

    def _features(self, audio):
        y = np.append(audio[0], audio[1:] - 0.97 * audio[:-1]).astype(np.float32)
        y = np.pad(y, self.n_fft // 2, mode='constant')
        frames = np.lib.stride_tricks.sliding_window_view(y, self.n_fft)[:: self.hop_length]
        power = np.abs(np.fft.rfft(frames * self.window, axis=-1)) ** 2
        feats = np.log(power @ self.mel.T + 2**-24).T  # [n_mels, T]
        valid = len(audio) // self.hop_length
        stats = feats[:, :valid]
        feats = (feats - stats.mean(axis=1, keepdims=True)) / (stats.std(axis=1, ddof=1, keepdims=True) + 1e-5)
        feats[:, valid:] = 0
        if self.pad_to:
            feats = np.pad(feats, ((0, 0), (0, (-feats.shape[1]) % self.pad_to)))
        return feats[np.newaxis].astype(np.float32)

    def transcribe(self, audio):
        feats = self._features(audio)
        length = np.array([len(audio) // self.hop_length], dtype=np.int64)
        inputs = {self.input_names[0]: feats}
        if len(self.input_names) > 1:
            inputs[self.input_names[1]] = length
        outputs = self.sess.run(None, inputs)
        logprobs = outputs[0]
        if len(outputs) > 1:
            valid_output = int(outputs[1][0])
        else:
            # Current NeMo exports remove the length input with conv masking.
            # All four architectures downsample by an integer factor and our
            # feature padding is a multiple of that factor.
            factor = feats.shape[2] // logprobs.shape[1]
            valid_output = (int(length[0]) + factor - 1) // factor
        ids = logprobs[0, :valid_output].argmax(axis=-1)
        out, prev = [], None
        for i in ids:
            if i != prev and i != self.blank:
                out.append(self.vocab[i])
            prev = i
        if self.wordpiece:
            words = []
            for token in out:
                if token in {'[PAD]', '[CLS]', '[SEP]', '[MASK]'}:
                    continue
                if token.startswith('##') and words:
                    words[-1] += token[2:]
                else:
                    words.append(token.removeprefix('##'))
            return ' '.join(words).strip()
        # Character models use " " tokens; SentencePiece models use "▁" word markers.
        return "".join(out).replace("▁", " ").strip()


MODELS = {
    "quartznet15x5": lambda t: NemoCtcOnnx("quartznet15x5", t),
    "citrinet256-ls": lambda t: NemoCtcOnnx("citrinet256-ls", t),
    "citrinet512-ls": lambda t: NemoCtcOnnx("citrinet512-ls", t),
    "citrinet1024-gamma-0.25": lambda t: NemoCtcOnnx("citrinet1024-gamma-0.25", t),
    "whisper-base": lambda t: FasterWhisper("base", t),
    "whisper-small": lambda t: FasterWhisper("small", t),
    "whisper-large-v3-turbo": lambda t: FasterWhisper("large-v3-turbo", t),
    "moonshine-tiny": lambda t: MoonshineOnnx("moonshine/tiny", t),
    "moonshine-streaming-tiny": lambda t: MoonshineStreaming("tiny", t),
    "moonshine-streaming-small": lambda t: MoonshineStreaming("small", t),
}
