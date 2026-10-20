"""Pure-Python checks of the quantised decimation filter (pytest; no simulator).

The requirement that matters for ASR: after 3:1 decimation, anything that folds into the
0-6.8 kHz band comes from 9.2-16 kHz, so the stopband must be deep from 9.2 kHz upward.
"""
import math
import re
from pathlib import Path

from decim3_coeffs import COEFFS, FRAC, TAPS


def gain_db(f, fs=48000.0):
    re_, im = 0.0, 0.0
    for n, c in enumerate(COEFFS):
        re_ += c * math.cos(2 * math.pi * f / fs * n)
        im -= c * math.sin(2 * math.pi * f / fs * n)
    return 20 * math.log10(max(math.hypot(re_, im) / (1 << FRAC), 1e-12))


def test_dc_gain_exactly_one():
    assert sum(COEFFS) == 1 << FRAC


def test_linear_phase():
    assert COEFFS == COEFFS[::-1]


def test_fits_dsp_b_port():
    assert len(COEFFS) == TAPS == 96
    assert all(-(1 << 17) <= c < (1 << 17) for c in COEFFS)


def test_passband_flat():
    worst = max(abs(gain_db(f)) for f in range(0, 6801, 50))
    assert worst < 0.01, f"passband ripple {worst:.4f} dB"


def test_stopband_protects_speech_band():
    worst = max(gain_db(f) for f in range(9200, 24001, 50))
    assert worst < -60.0, f"stopband only {worst:.1f} dB"


def test_rtl_include_matches_golden():
    vh = (Path(__file__).resolve().parent.parent / "rtl" / "decim3_coeffs.vh").read_text()
    vals = []
    for sign, mag in re.findall(r"= (-?)18'sd(\d+);", vh):
        vals.append(-int(mag) if sign else int(mag))
    assert vals[:TAPS] == COEFFS
