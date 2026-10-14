"""Experimental sparse mel projection; not a replacement for the pinned frontend.

The checkpoint's 80x257 filterbank has only 500 nonzero coefficients. Restrict
each mel dot product to its nonzero support. Floating-point reduction order
can differ, so feature/model/accuracy checks must precede deployment.
"""
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'software/model-tools'))
from citrinet_cpu import Frontend


class SparseFrontend(Frontend):
    def __init__(self, model_dir):
        super().__init__(model_dir)
        self.bands = []
        for row in self.fb:
            indices = np.flatnonzero(row)
            if not len(indices):
                raise ValueError('Empty mel filter')
            first, last = int(indices[0]), int(indices[-1])+1
            self.bands.append((first, last, np.ascontiguousarray(row[first:last])))

    def __call__(self, audio):
        if len(audio) < 320:
            raise ValueError('Audio is too short for reflected STFT')
        audio = np.asarray(audio, dtype=np.float32)
        emphasized = np.concatenate((audio[:1], audio[1:] - np.float32(.97)*audio[:-1]))
        frames = np.lib.stride_tricks.sliding_window_view(
            np.pad(emphasized, (256,256), mode='reflect'), 512)[::160]
        spectrum = np.fft.rfft(frames*self.window, axis=-1).astype(np.complex64)
        power = (spectrum.real*spectrum.real + spectrum.imag*spectrum.imag).T
        mel = np.empty((80, power.shape[1]), dtype=np.float32)
        for i, (first, last, weights) in enumerate(self.bands):
            mel[i] = weights @ power[first:last]
        features = np.log(mel + np.float32(2**-24)).astype(np.float32)
        valid = len(audio)//160+1
        mean = features[:,:valid].mean(1, keepdims=True)
        std = features[:,:valid].std(1, ddof=1, keepdims=True)
        features = (features-mean)/(std+np.float32(1e-5))
        features[:,valid:] = 0
        features = np.pad(features, ((0,0),(0,(-features.shape[-1])%16)))
        return np.ascontiguousarray(features[None],dtype=np.float32), np.array([valid],dtype=np.int64)
