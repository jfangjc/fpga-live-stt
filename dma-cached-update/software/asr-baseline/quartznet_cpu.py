#!/usr/bin/env python3
"""Experimental FP32 QuartzNet CPU baseline; no FPGA inference calls.

Frontend follows NeMo per-feature normalization and Slaney mel filters.
Only valid frames enter the exported graph, whose convolution masks are disabled.
"""
import argparse
import json
import time
import wave
from pathlib import Path

import numpy as np
import onnxruntime as ort


def read_pcm24(path):
    with wave.open(str(path), 'rb') as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 3, 16000):
            raise ValueError('Expected mono 24-bit PCM WAV at 16000 Hz')
        data = np.frombuffer(source.readframes(source.getnframes()), dtype=np.uint8)
    data = data.reshape(-1, 3).astype(np.int32)
    pcm = data[:, 0] | (data[:, 1] << 8) | (data[:, 2] << 16)
    pcm = (pcm ^ (1 << 23)) - (1 << 23)
    return pcm.astype(np.float32) / np.float32(1 << 23)


def slaney_mel_filters(n_mels=64):
    # Slaney's linear scale below 1 kHz and log scale above it, as in librosa.
    step = 200.0 / 3.0
    log_step = np.log(6.4) / 27.0
    maximum = 15.0 + np.log(8000.0 / 1000.0) / log_step
    mel_points = np.linspace(0.0, maximum, n_mels + 2)
    hz = step * mel_points
    mask = mel_points >= 15.0
    hz[mask] = 1000.0 * np.exp(log_step * (mel_points[mask] - 15.0))
    frequencies = np.fft.rfftfreq(512, 1.0 / 16000)
    ramps = hz[:, None] - frequencies[None, :]
    widths = np.diff(hz)
    filters = np.maximum(0.0, np.minimum(-ramps[:-2] / widths[:-1, None],
                                        ramps[2:] / widths[1:, None]))
    filters = filters.astype(np.float32)
    filters *= (2.0 / (hz[2:] - hz[:-2]))[:, None]
    return filters


def frontend(audio):
    if len(audio) < 512:
        raise ValueError('Recording must contain at least 512 samples')
    emphasized = audio.copy()
    emphasized[1:] -= np.float32(0.97) * audio[:-1]
    padded = np.pad(emphasized, (256, 256), mode='reflect')
    frames = np.lib.stride_tricks.sliding_window_view(padded, 512)[::160]
    window = np.pad(np.hanning(320).astype(np.float32), (96, 96))
    spectrum = np.abs(np.fft.rfft(frames * window)).astype(np.float32) ** 2
    features = np.log(slaney_mel_filters() @ spectrum.T + np.float32(2 ** -24))
    # Original NeMo 1.0.0rc1 uses ceil(N / hop), then masks the extra STFT frame.
    # transcribe() disables dither and feature padding (pad_to=0).
    valid = (len(audio) + 159) // 160
    features = (features - features[:, :valid].mean(axis=1, keepdims=True)) / (
        features[:, :valid].std(axis=1, ddof=1, keepdims=True) + np.float32(1e-5))
    features[:, valid:] = 0
    return features[None].astype(np.float32), valid


def decode(logprobs, vocab, valid_frames):
    tokens = np.argmax(logprobs[0, :valid_frames], axis=-1)
    blank = next(i for i, t in vocab.items() if t == '<blk>')
    previous = None
    text = []
    for token in tokens:
        if token != previous and token != blank:
            text.append(vocab[int(token)])
        previous = token
    return ''.join(text).replace('▁', ' ').strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wav', type=Path)
    parser.add_argument('--model', type=Path, default=Path(__file__).parent / 'model')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--remove-dc', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.threads <= 64:
        parser.error('--threads must be between 1 and 64')
    audio = read_pcm24(args.wav)
    if args.remove_dc:
        audio -= audio.mean()
    vocab = {}
    for line in (args.model / 'vocab.txt').read_text(encoding='utf-8').splitlines():
        token, index = line.rsplit(' ', 1)
        vocab[int(index)] = token
    config = json.loads((args.model / 'config.json').read_text())
    if config.get('features_size') != 64 or config.get('subsampling_factor') != 2:
        raise ValueError('Unexpected model configuration')
    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(args.model / 'model.onnx'), options,
                                   providers=['CPUExecutionProvider'])
    if [i.name for i in session.get_inputs()] != ['audio_signal']:
        raise ValueError('Unexpected graph inputs')
    start = time.perf_counter()
    features, valid = frontend(audio)
    processed = time.perf_counter()
    output = session.run(['logprobs'], {'audio_signal': features[:, :, :valid].copy()})[0]
    inferred = time.perf_counter()
    text = decode(output, vocab, (valid + 1) // 2)
    ended = time.perf_counter()
    print(json.dumps({'transcript': text, 'audio_seconds': len(audio) / 16000,
                      'frontend_seconds': processed - start,
                      'inference_seconds': inferred - processed,
                      'decode_seconds': ended - inferred,
                      'total_seconds': ended - start,
                      'real_time_factor': (ended - start) / (len(audio) / 16000),
                      'remove_dc': args.remove_dc, 'threads': args.threads,
                      'provider': session.get_providers()}, indent=2))


if __name__ == '__main__':
    main()
