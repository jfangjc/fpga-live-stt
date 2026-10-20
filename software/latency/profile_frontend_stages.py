"""Attribute the unchanged pinned frontend; no FPGA or performance acceptance claim."""
import argparse
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'software/model-tools'))
from citrinet_cpu import Frontend, read_audio
ap = argparse.ArgumentParser()
ap.add_argument('--runs', type=int, default=100)
ap.add_argument('--out', type=Path, required=True)
a = ap.parse_args()
frontend = Frontend(ROOT/'research/export/citrinet-256-ls')
audio = read_audio(ROOT/'research/eval/user-recording/speech.wav')
contexts = []
for seconds in (.5, 1, 2.5):
    clip = np.ascontiguousarray(audio[:round(seconds*16000)])
    expected, expected_length = frontend(clip)
    rows = []
    for i in range(10+a.runs):
        marks = [time.perf_counter()]
        emphasized = np.concatenate((clip[:1], clip[1:]-np.float32(.97)*clip[:-1]))
        frames = np.lib.stride_tricks.sliding_window_view(np.pad(emphasized,(256,256),mode='reflect'),512)[::160]
        marks.append(time.perf_counter())
        spectrum = np.fft.rfft(frames*frontend.window,axis=-1).astype(np.complex64)
        marks.append(time.perf_counter())
        power = (spectrum.real*spectrum.real+spectrum.imag*spectrum.imag).T
        marks.append(time.perf_counter())
        mel = frontend.fb @ power
        marks.append(time.perf_counter())
        features = np.log(mel+np.float32(2**-24)).astype(np.float32)
        marks.append(time.perf_counter())
        valid = len(clip)//160+1
        mean = features[:,:valid].mean(1,keepdims=True)
        std = features[:,:valid].std(1,ddof=1,keepdims=True)
        features = (features-mean)/(std+np.float32(1e-5))
        marks.append(time.perf_counter())
        features[:,valid:] = 0
        features = np.pad(features,((0,0),(0,(-features.shape[-1])%16)))
        actual = np.ascontiguousarray(features[None],dtype=np.float32)
        length = np.array([valid],dtype=np.int64)
        marks.append(time.perf_counter())
        np.testing.assert_array_equal(actual,expected)
        np.testing.assert_array_equal(length,expected_length)
        if i>=10: rows.append(np.diff(marks).tolist())
    names = ('preemphasis_and_frames','window_and_fft','power','mel_projection','log',
             'normalization','padding_and_output')
    contexts.append({'context_seconds':seconds,'features_bit_exact':True,
                     'stage_median_ms':dict(zip(names,(1000*np.median(rows,axis=0)).tolist())),
                     'instrumented_total_p50_ms':float(1000*np.median(np.sum(rows,axis=1)))})
report = {'complete':True,'hardware_execution':False,'profiling_only':True,'runs_per_context':a.runs,
          'contexts':contexts,'scipy_available':importlib.util.find_spec('scipy') is not None,
          'numpy_version':np.__version__,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'pinned_frontend_sha256':hashlib.sha256((ROOT/'software/model-tools/citrinet_cpu.py').read_bytes()).hexdigest(),
          'note':'Instrumentation overhead is included. Not a CPU/FPGA comparison; no preprocessing changes.'}
a.out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
