"""Private valid-frame frontend for runtimes that immediately crop padding.

All preprocessing arithmetic is copied from the pinned frontend. The output
contains only valid frames; callers must use that explicit input contract.
The original public frontend remains unchanged.
"""
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/model-tools'))
from citrinet_cpu import Frontend

class ValidFrameFrontend(Frontend):
    def __call__(self, audio):
        if len(audio) < 320:
            raise ValueError('Audio is too short for reflected STFT')
        audio = np.asarray(audio, dtype=np.float32)
        emphasized = np.concatenate((audio[:1], audio[1:] - np.float32(0.97) * audio[:-1]))
        frames = np.lib.stride_tricks.sliding_window_view(np.pad(emphasized, (256, 256), mode='reflect'), 512)[::160]
        spectrum = np.fft.rfft(frames * self.window, axis=-1).astype(np.complex64)
        power = (spectrum.real * spectrum.real + spectrum.imag * spectrum.imag).T
        features = np.log(self.fb @ power + np.float32(2 ** (-24))).astype(np.float32)
        valid = len(audio) // 160 + 1
        mean = features[:, :valid].mean(1, keepdims=True)
        std = features[:, :valid].std(1, ddof=1, keepdims=True)
        features = (features - mean) / (std + np.float32(1e-05))
        features[:, valid:] = 0
        return (np.ascontiguousarray(features[None], dtype=np.float32), np.array([valid], dtype=np.int64))
