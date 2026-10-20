#!/usr/bin/env python3
"""Capture benchmark for audio_capture_axi: drops, reader CPU cost and signal checks under load.

Run on the board (root, overlay loaded):
  sudo python3 sw/bench_capture.py --seconds 1800 --hop-ms 250 --load-ms 170 --out t4_spin170.json
Dry run anywhere (simulated device, no hardware):
  python3 sw/bench_capture.py --fake --seconds 5 --load-ms 0 --out /tmp/fake.json

The load option emulates inference: N worker processes pinned to cores busy-spin for
--load-ms out of every --hop-ms, like the 4 ORT threads of a 2.55 s window (CPU 169.5 ms,
shortwide 147.7 ms per window, measured). --load-only runs just the load, for pairing with the
OLD capture script on the old firmware (old vs new reader cost).
"""
import argparse
import glob
import json
import math
import multiprocessing as mp
import os
import platform
import threading
import time

from audio_ring import CDC, CTRL, DEPTH, ID, MAGIC, OVR, RCNT, RING, SAT, STATUS, WCNT, AudioRing, UioWindow

FS = 16000


def find_uio(name="voice-prototype"):
    for path in sorted(glob.glob("/sys/class/uio/uio*/name")):
        if open(path).read().strip() == name:
            return "/dev/" + path.split("/")[-2]
    raise SystemExit(f"no UIO device named {name!r}; is the overlay loaded?")


def spin_worker(core, hop_s, busy_s, stop_at):
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {core})
    nxt = time.monotonic()
    while time.monotonic() < stop_at:
        t_end = time.monotonic() + busy_s
        while time.monotonic() < t_end:
            pass
        nxt += hop_s
        time.sleep(max(0.0, nxt - time.monotonic()))


def start_load(workers, hop_s, busy_s, seconds):
    if busy_s <= 0 or workers <= 0:
        return []
    stop_at = time.monotonic() + seconds
    procs = [mp.Process(target=spin_worker, args=(i % (os.cpu_count() or 1), hop_s, busy_s, stop_at), daemon=True)
             for i in range(workers)]
    for p in procs:
        p.start()
    return procs


class FakeDevice:
    """16 kHz producer thread: 1 kHz tone at -30 dBFS on L, 2.5 kHz on R, plus DC on L."""

    def __init__(self, depth=8192):
        self.depth, self.mem, self.w, self.r = depth, [0] * depth, 0, 0
        self.regs = {ID: MAGIC, DEPTH: depth, CTRL: 0, STATUS: 0, OVR: 0, SAT: 0, CDC: 0}
        self.t0 = time.monotonic()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        a = int(32768 * 10 ** (-30 / 20))
        while True:
            due = int((time.monotonic() - self.t0) * FS)
            while self.w < due:
                n = self.w
                l = int(a * math.sin(2 * math.pi * 1000 * n / FS)) + 200
                r = int(a * math.sin(2 * math.pi * 2500 * n / FS))
                if ((self.w - self.r) & 0xFFFFFFFF) >= self.depth:
                    self.regs[OVR] += 1
                self.mem[n % self.depth] = ((r & 0xFFFF) << 16) | (l & 0xFFFF)
                self.w += 1
            time.sleep(0.002)

    def read32(self, off):
        return self.w & 0xFFFFFFFF if off == WCNT else self.regs.get(off, 0)

    def write32(self, off, v):
        if off == RCNT:
            self.r = v
        self.regs[off] = v

    def read_block(self, off, n):
        i = (off - RING) // 4
        return self.mem[i:i + n]


def goertzel_dbfs(x, f):
    if not x:
        return float("-inf")
    w = 2 * math.pi * f / FS
    c = 2 * math.cos(w)
    s1 = s2 = 0.0
    for v in x:
        s1, s2 = v + c * s1 - s2, s1
    amp = 2 * math.sqrt(max(s1 * s1 + s2 * s2 - c * s1 * s2, 0.0)) / len(x)
    return 20 * math.log10(max(amp / 32768, 1e-12))


def pct(v, q):
    if not v:
        return None
    s = sorted(v)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--device", help="UIO device (default: find by name voice-prototype)")
    p.add_argument("--fake", action="store_true", help="simulated device, for a dry run without hardware")
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--hop-ms", type=float, default=250.0, help="reader poll period = ASR hop")
    p.add_argument("--load-ms", type=float, default=0.0, help="busy time per hop per load worker (0 = no load)")
    p.add_argument("--load-workers", type=int, default=4)
    p.add_argument("--load-only", action="store_true", help="only run the load (pair with the old capture script)")
    p.add_argument("--gain-shift", type=int, default=4, choices=range(0, 9))
    p.add_argument("--tone-hz", type=float, default=1000.0, help="tone to measure (Goertzel), e.g. phone tone app")
    p.add_argument("--keep-audio-s", type=float, default=10.0, help="seconds of audio kept for signal checks")
    p.add_argument("--out", required=True)
    a = p.parse_args()

    hop_s, busy_s = a.hop_ms / 1000, a.load_ms / 1000
    if a.load_only:
        procs = start_load(a.load_workers, hop_s, busy_s, a.seconds)
        for proc in procs:
            proc.join()
        json.dump({"mode": "load_only", "seconds": a.seconds, "hop_ms": a.hop_ms, "load_ms": a.load_ms,
                   "load_workers": a.load_workers}, open(a.out, "w"), indent=1)
        return

    dev = FakeDevice() if a.fake else UioWindow(a.device or find_uio())
    ring = AudioRing(dev)
    ring.start(gain_shift=a.gain_shift)
    time.sleep(0.05)
    ring.read()                                    # discard wake-up / DC-blocker settling
    procs = start_load(a.load_workers, hop_s, busy_s, a.seconds)

    keep = int(a.keep_audio_s * FS)
    left, right = [], []
    read_us, gaps_ms = [], []
    frames = 0
    t_start = time.monotonic()
    w_start = dev.read32(WCNT)
    cpu0 = time.process_time()
    last = t_start
    nxt = t_start
    while True:
        nxt += hop_s
        time.sleep(max(0.0, nxt - time.monotonic()))
        now = time.monotonic()
        gaps_ms.append((now - last) * 1000)
        last = now
        t0 = time.perf_counter()
        l, r, _ = ring.read()
        read_us.append((time.perf_counter() - t0) * 1e6)
        frames += len(l)
        if len(left) < keep:
            left.extend(l[:keep - len(left)])
            right.extend(r[:keep - len(right)])
        if now - t_start >= a.seconds:
            break
    cpu = time.process_time() - cpu0
    wall = time.monotonic() - t_start
    w_end = dev.read32(WCNT)
    counters = ring.counters()
    ring.stop()
    for proc in procs:
        proc.join(timeout=1)

    mean = lambda v: sum(v) / len(v) if v else 0.0
    rms_dbfs = lambda v: 20 * math.log10(max(math.sqrt(mean([x * x for x in v])) / 32768, 1e-12)) if v else None
    hw_rate = ((w_end - w_start) & 0xFFFFFFFF) / wall
    result = {
        "mode": "fake" if a.fake else "board",
        "host": platform.uname()._asdict(),
        "settings": vars(a),
        "wall_s": wall,
        "frames_read": frames,
        "hw_frame_rate_hz": hw_rate,
        "frame_rate_error_ppm": (hw_rate / FS - 1) * 1e6,
        "software_lost": counters["software_lost"],
        "hw_overruns": counters["overruns"],
        "cdc_drops": counters["cdc_drops"],
        "saturated_samples": counters["saturated"],
        "reader_cpu_percent_of_one_core": 100 * cpu / wall,
        "read_call_us": {"p50": pct(read_us, .5), "p95": pct(read_us, .95), "max": max(read_us)},
        "gap_between_reads_ms": {"p50": pct(gaps_ms, .5), "p95": pct(gaps_ms, .95), "max": max(gaps_ms)},
        "ring_headroom_x": (dev.read32(DEPTH) / FS * 1000) / max(gaps_ms),
        "left": {"dc_lsb": mean(left), "rms_dbfs": rms_dbfs(left), "tone_dbfs": goertzel_dbfs(left, a.tone_hz)},
        "right": {"dc_lsb": mean(right), "rms_dbfs": rms_dbfs(right), "tone_dbfs": goertzel_dbfs(right, a.tone_hz)},
    }
    with open(a.out, "w") as f:
        json.dump(result, f, indent=1)
    print(json.dumps({k: result[k] for k in ("frames_read", "hw_frame_rate_hz", "software_lost", "hw_overruns",
                                             "cdc_drops", "reader_cpu_percent_of_one_core", "gap_between_reads_ms",
                                             "ring_headroom_x")}, indent=1))
    lost = result["software_lost"] + result["hw_overruns"] + result["cdc_drops"]
    raise SystemExit(0 if lost == 0 else 1)


if __name__ == "__main__":
    main()
