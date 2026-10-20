#!/usr/bin/env python3
"""PS-side reader for audio_capture_axi (replaces the per-sample FIFO pops in kv260_voice.py).

The PL writes 16 kHz stereo frames into a ring buffer and counts them (WRITE_CNT).
Software copies everything new in one pass whenever it likes, then publishes READ_CNT.
Nothing is lost unless software falls a whole ring (0.512 s by default) behind, and the
hardware counts that too.

Device memory rule (same as kv260_voice.py): only aligned 32-bit loads and stores; never
memcpy or byte access on the UIO mapping. UioWindow uses a ctypes uint32 array, whose
slicing performs one 32-bit load per element. [UNVERIFIED on the board: check for SIGBUS.]
"""
import argparse
import ctypes
import mmap
import os
import sys
import time
import wave

ID, CTRL, STATUS, DEPTH, WCNT, RCNT, FILL, OVR, SAT, CDC, THR, PARAMS = range(0, 48, 4)
RING = 0x8000
MAGIC = 0x41554431
MASK = 0xFFFFFFFF
SAFETY = 64          # frames (4 ms): never read the slots the writer is about to overwrite


def to_s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class UioWindow:
    """64 KB UIO register window with aligned 32-bit access only."""

    def __init__(self, path="/dev/uio0", size=0x10000):
        if sys.byteorder != "little":
            raise RuntimeError("little-endian CPU required")
        fd = os.open(path, os.O_RDWR | os.O_SYNC)
        try:
            self.mm = mmap.mmap(fd, size, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        finally:
            os.close(fd)
        self.words = (ctypes.c_uint32 * (size // 4)).from_buffer(self.mm)

    def read32(self, off):
        return self.words[off >> 2]

    def write32(self, off, value):
        self.words[off >> 2] = value & MASK

    def read_block(self, off, n):
        i = off >> 2
        return list(self.words[i:i + n]) if n > 0 else []


class AudioRing:
    def __init__(self, dev):
        self.dev = dev
        ident = dev.read32(ID)
        if ident != MAGIC:
            raise RuntimeError(f"audio_capture_axi not found (ID 0x{ident:08x}); is the overlay loaded?")
        self.depth = dev.read32(DEPTH)
        self.safety = min(SAFETY, self.depth // 4)
        self.rcount = 0
        self.lost = 0

    def start(self, gain_shift=4, irq=False, threshold=4000):
        d = self.dev
        d.write32(CTRL, gain_shift << 8)                     # disable first: gain is quasi-static
        d.write32(THR, threshold)
        d.write32(CTRL, (1 << 31) | (gain_shift << 8))       # clear counters while stopped
        d.write32(CTRL, (gain_shift << 8) | (2 if irq else 0) | 1)
        self.rcount = 0
        self.lost = 0

    def stop(self):
        self.dev.write32(CTRL, self.dev.read32(CTRL) & ~1 & MASK)

    def read(self, max_frames=None):
        """Return (left, right, lost) with int16 lists for all frames since the last call."""
        d = self.dev
        w = d.read32(WCNT)
        avail = (w - self.rcount) & MASK
        lost = 0
        limit = self.depth - self.safety
        if avail > limit:                                     # too far behind: skip the oldest
            lost = avail - limit
            self.rcount = (self.rcount + lost) & MASK
            avail = limit
        n = avail if max_frames is None else min(avail, max_frames)
        start = self.rcount % self.depth
        first = min(n, self.depth - start)
        words = d.read_block(RING + 4 * start, first) + d.read_block(RING, n - first)
        # Anything the writer lapped while we were copying is unreliable: drop it.
        lapped = ((d.read32(WCNT) - self.rcount) & MASK) - self.depth
        if lapped > 0:
            drop = min(lapped, n)
            words = words[drop:]
            lost += drop
        self.rcount = (self.rcount + n) & MASK
        d.write32(RCNT, self.rcount)
        self.lost += lost
        return [to_s16(x) for x in words], [to_s16(x >> 16) for x in words], lost

    def counters(self):
        d = self.dev
        return {"write": d.read32(WCNT), "fill": d.read32(FILL), "overruns": d.read32(OVR),
                "saturated": d.read32(SAT), "cdc_drops": d.read32(CDC), "status": d.read32(STATUS),
                "software_lost": self.lost}


def main():
    p = argparse.ArgumentParser(description="Capture stereo 16 kHz audio from audio_capture_axi to a WAV file")
    p.add_argument("--device", default="/dev/uio0")
    p.add_argument("--seconds", type=float, default=5.0)
    p.add_argument("--gain-shift", type=int, default=4, choices=range(0, 9))
    p.add_argument("--discard-ms", type=float, default=50.0, help="mic wake-up and DC-blocker settling")
    p.add_argument("--poll-ms", type=float, default=50.0)
    p.add_argument("output")
    a = p.parse_args()
    ring = AudioRing(UioWindow(a.device))
    ring.start(gain_shift=a.gain_shift)
    time.sleep(a.discard_ms / 1000)
    ring.read()
    frames = bytearray()
    deadline = time.monotonic() + a.seconds
    while time.monotonic() < deadline:
        time.sleep(a.poll_ms / 1000)
        left, right, _ = ring.read()
        for l, r in zip(left, right):
            frames += l.to_bytes(2, "little", signed=True) + r.to_bytes(2, "little", signed=True)
    ring.stop()
    with wave.open(a.output, "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(bytes(frames))
    print(ring.counters())


if __name__ == "__main__":
    main()
