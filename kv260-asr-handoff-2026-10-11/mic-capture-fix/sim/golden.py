"""Bit-exact golden models for the audio capture pipeline.

Pure Python integers: exact at any width, and Python's >> on negative numbers floors,
matching Verilog's >>> on signed values. Every function mirrors one RTL module.
"""
from decim3_coeffs import COEFFS, FRAC


def sat(v, bits):
    hi = (1 << (bits - 1)) - 1
    lo = -(1 << (bits - 1))
    return hi if v > hi else lo if v < lo else v


def decim3(x, h=COEFFS):
    """rtl/decim3_fir.v: one output after every third input, newest sample x[3m+2]."""
    out = []
    taps = len(h)
    for n in range(2, len(x), 3):
        acc = 0
        for k in range(taps):
            if n - k >= 0:
                acc += h[k] * x[n - k]
        out.append(sat((acc + (1 << (FRAC - 1))) >> FRAC, 20))
    return out


def dc_gain(xs, gain_shift=4, k=9):
    """rtl/dc_gain.v: returns list of (y16, sat_flag)."""
    s = 0
    xp = 0
    g = min(gain_shift, 8)
    out = []
    for x in xs:
        s_next = s + ((x - xp) << k) - (s >> k)
        y_dc = (s_next + (1 << (k - 1))) >> k
        r = ((y_dc << g) + 2) >> 2
        y = sat(r, 16)
        out.append((y, int(y != r)))
        s = s_next
        xp = x
    return out


def pipeline(left18, right18, gain_shift=4):
    """Whole audio-domain chain: 48 kHz 18-bit stereo -> packed 32-bit ring words + sat flags."""
    l = dc_gain(decim3(left18), gain_shift)
    r = dc_gain(decim3(right18), gain_shift)
    words = [((ry & 0xFFFF) << 16) | (ly & 0xFFFF) for (ly, _), (ry, _) in zip(l, r)]
    sats = [ls + rs for (_, ls), (_, rs) in zip(l, r)]
    return words, sats


def to_s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v
