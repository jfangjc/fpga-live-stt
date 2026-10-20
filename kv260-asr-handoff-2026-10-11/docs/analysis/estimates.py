import json, math, re, sys
A = sys.argv[1]
L = json.load(open(A))  # (name, kind, macs_per_s, weights, out_fps, cin, cout, k)
F = 100e6
print("== 1. Amdahl bounds from measured shortwide (reports/fused/shortwide_counter_comparison.json, 64-lane rows)")
rows = {0.5: dict(front=4.154, model=58.081, decode=0.125, ioctl=5.723, pack=0.299, unpack=0.426, active=4.048, outside=51.290, cpu_p50=69.220, fpga_p50=62.396),
        1.0: dict(front=6.094, model=86.283, decode=0.154, ioctl=7.985, pack=0.330, unpack=0.539, active=6.081, outside=77.392, cpu_p50=105.250, fpga_p50=92.626)}
pl_share = 0.4347  # computed: 32 selected pairs / all model MACs
for c, r in rows.items():
    cpu_side = r["outside"] + r["front"] + r["decode"]
    ceiling = 1 - cpu_side / r["cpu_p50"]
    busy = r["active"] / r["fpga_p50"]
    proj_pl = r["active"] / pl_share
    proj_total = r["front"] + r["decode"] + proj_pl + 1.0  # +1 ms one-ioctl/sync allowance (estimate)
    print(f"ctx {c}s: PL busy {busy:.1%} of wall; CPU-side floor {cpu_side:.1f} ms -> max reduction with this partition {ceiling:.1%}; "
          f"whole-model-in-PL at same efficiency: PL {proj_pl:.1f} ms, total ~{proj_total:.1f} ms -> {1-proj_total/r['cpu_p50']:.0%} lower than CPU")
macs_1s_pairs = pl_share * 271.2528e6 * 1.01
print(f"effective PL MAC/cycle at 1 s: {macs_1s_pairs/608096:.0f} of 512 peak ({macs_1s_pairs/608096/512:.0%})")

print("\n== 2. Whole-encoder PL cycle model for one window (T0 input frames)")
def cycles(T0, Ldw, pw_t=16, pw_m=32, overlap=False):
    tot = 0; per = []
    for n, kind, mps, w, fps, cin, cout, k in L:
        T = max(1, round(T0 * fps / 100.0))
        if kind == "dw":
            c = cin * math.ceil(T / Ldw) * k
        elif kind in ("pw", "pw_res"):
            c = math.ceil(T / pw_t) * math.ceil(cout / pw_m) * cin
        elif kind == "se":
            c = 2 * cin * math.ceil(T / Ldw)  # mean pass + scale pass over on-chip buffer
        per.append((n, kind, c)); tot += c
    if overlap:  # dw of layer i hidden behind pw of same pair (perfect overlap upper bound)
        tot2 = 0; i = 0
        while i < len(per):
            if per[i][1] == "dw" and i + 1 < len(per) and per[i+1][1] == "pw":
                tot2 += max(per[i][2], per[i+1][2]); i += 2
            else:
                tot2 += per[i][2]; i += 1
        return tot2
    return tot
for T0 in (256, 101, 51):
    macs = sum(x[2] for x in L) * T0 / 100.0
    for Ldw in (64, 128, 256):
        s = cycles(T0, Ldw); o = cycles(T0, Ldw, overlap=True)
        print(f"T0={T0:3d} ({T0/100:.2f}s) MACs={macs/1e6:6.1f}M  dw lanes={Ldw:3d}: sequential {s/F*1e3:5.1f} ms, overlapped {o/F*1e3:5.1f} ms, ideal@512 {macs/512/F*1e3:5.1f} ms")

print("\n== 3. Memory budget (bytes)")
W = sum(x[3] for x in L)
blk = {}
for n, kind, mps, w, fps, cin, cout, k in L:
    b = n.split(".")[0]; blk[b] = blk.get(b, 0) + w
maxblk = max(blk.values())
act = max(x[5] * round(256 * x[4] / 100.0) for x in L)
URAM = 64 * 4096 * 72 // 8; BRAM = 144 * 36 * 1024 // 8
print(f"model INT8 weights {W:,} B; max block weights {maxblk:,} B; double-buffered {2*maxblk:,} B")
print(f"largest activation tensor at 256 frames: {act:,} B; 4 buffers (in, out, residual, scratch) {4*act:,} B")
print(f"URAM total {URAM:,} B; BRAM total {BRAM:,} B; on-chip total {URAM+BRAM:,} B")
print(f"weights/on-chip = {W/(URAM+BRAM):.2f}x")
for H in (0.5, 0.25):
    print(f"hop {H}s: weight stream {W/H/1e6:.1f} MB/s; per-window stream time at 1.6 GB/s peak {W/1.6e9*1e3:.1f} ms, at 0.8 GB/s {W/0.8e9*1e3:.1f} ms")

print("\n== 4. Live duty cycle (compute per window / hop)")
for name, per_win_ms in (("CPU-only (LONG_INPUT 2.55 s p50)", 169.50), ("shortwide FPGA (2.55 s p50)", 147.70), ("whole-encoder PL est. (overlapped, 128 dw lanes) + 10 ms PS", cycles(256,128,overlap=True)/F*1e3 + 10)):
    print(f"{name}: {per_win_ms:.1f} ms -> duty {per_win_ms/500:.0%} @0.5 s hop, {per_win_ms/250:.0%} @0.25 s hop")

print("\n== 5. Two-mic delay-and-sum gain (broadside) in diffuse noise, averaged 300-4000 Hz")
c = 343.0
for d in (0.02, 0.05, 0.10):
    gs = []
    for f in range(300, 4001, 50):
        x = 2 * math.pi * f * d / c
        coh = math.sin(x) / x
        gs.append(2 / (1 + coh))
    g = sum(gs) / len(gs)
    alias = c / (2 * d)
    print(f"d={d*1000:.0f} mm: mean diffuse gain {10*math.log10(g):.2f} dB (white-noise gain 3.01 dB); spatial alias above {alias:.0f} Hz; "
          f"max TDOA {d/c*1e6:.0f} us = {d/c*16000:.2f} samples@16k, {d/c*48000:.2f} samples@48k; "
          f"integer-sample resolution near broadside @48k {math.degrees(math.asin(min(1,c/(48000*d)))):.1f} deg")

print("\n== 6. Mic clocking")
print(f"current BCLK 1.024 MHz vs datasheet min 2.048 MHz; sleep threshold 0.9 MHz")
print(f"NCO edge quantisation at 100 MHz: uniform +-5 ns -> RMS {10/math.sqrt(12):.2f} ns vs datasheet TIE 2 ns RMS")
print(f"NCO at 300 MHz: RMS {3.333/math.sqrt(12):.2f} ns")
print(f"FIFO depth 1024 @16 kHz = {1024/16000*1e3:.0f} ms vs 2.55 s window CPU inference 169.5 ms")

print("\n== 7. Emission latency model (s): word end -> pixels; hop H, right context R, compute C, display D=17 ms (1 frame @60 Hz)")
for H, R, C in ((0.5, 1.03, 0.148), (0.5, 0.5, 0.148), (0.25, 0.25, 0.04), (0.25, 0.5, 0.04), (0.25, 0.25, 0.148)):
    D = 0.017
    print(f"H={H} R={R} C={C}: mean {H/2+R+C+D:.2f}, worst {H+R+C+D:.2f}")
