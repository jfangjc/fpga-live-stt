# Integrating `audio_capture_axi` into the shortwide design

**Status:** RTL complete. Verilator `-Wall` lint is clean, and 22/22 cocotb tests and 11/11 pytest checks pass. **Nothing here has been synthesised, built or run on the board yet.**

**Evidence tags** (as in `../../docs/ARCHITECTURE_REVIEW.md`):
- **[M]** measured, with a file;
- **[C]** computed;
- **[E]** estimated;
- **[UNVERIFIED]** not checked yet.

Snapshot paths are relative to the repository root.

---

## 1. Changes required

### 1.1 Bench wiring

| Item | Change |
|---|---|
| Mic #1 (existing) | No change: SEL → GND (left), BCLK D11, WS (LRCL) B10, DOUT E12 |
| Mic #2 (optional, for direction-of-arrival later) | Wire it in parallel on BCLK, LRCL and DOUT with **SEL → 3V3** (right slot). The datasheet recommends a **100 kΩ pull-down on DOUT** for the shared line. No new FPGA pins |
| Spacing | About 100 mm between mics if DOA is wanted (4.1° resolution at 48 kHz **[C]**) |

### 1.2 Vivado project

1. **Sources.**
   - Add `rtl/audio_capture_axi.v`, `rtl/i2s_rx_stereo.v`, `rtl/decim3_fir.v` and `rtl/dc_gain.v`.
   - Add `rtl/decim3_coeffs.vh`: set it as a Verilog Header and add `rtl/` to the include path (`decim3_fir.v` does `` `include "decim3_coeffs.vh" ``).
   - Remove `rtl/voice_axi.v`, `rtl/sph0645_rx.v` and `rtl/qn_mac.v`. `qn_mac` is only used by `voice_axi`, and only for the `kv260_voice.py` bring-up harness; the inference runtime uses the AXI DMA and the `qn_tile` driver.
2. **Block design.** Run `scripts/bd_patch_audio.tcl` with the BD open, or follow its steps by hand. It:
   - adds `clk_wiz` (pl_clk0 99.999001 MHz → **24.576 MHz**, `locked` used). The best MMCM setting is D = 1, M = 10.875, O = 44.25 → 24.576026 MHz, +1 ppm, VCO 1,087.5 MHz **[C]**. Confirm `CLKOUT1_ACTUAL_FREQ` in Vivado **[UNVERIFIED]**;
   - replaces the `voice` module reference with `audio_capture_axi`, keeping the **same instance name**;
   - reconnects `axi_sc/M00_AXI`, `pl_clk0`, `reset/peripheral_aresetn`, `irq_concat/In0` and the `mic_*` ports;
   - keeps the address segment at **0xA000_0000, 64 KB**.
3. **Constraints.** Replace `hardware/mic_cdc.xdc` with `constraints/audio_cdc.xdc`. Keep `hardware/pmod.xdc`. After the build, confirm that each `get_cells`/`get_pins` matches at least one object and that `report_cdc` shows no unsafe crossings.
4. **Build checks.**
   - Routed timing met on both clocks.
   - `report_clock_interaction`: only the excepted paths cross.
   - `report_cdc` clean.
   - `report_utilization -hierarchical`: record the before/after delta in §2.2.
5. **Firmware.** Package it as a new application, e.g. `asr-v3-shortwide-audio`. Keep `asr-v3-shortwide` unchanged for rollback.

### 1.3 Device tree

**No change needed.** The node `voice@a0000000` (`deployment/asr-v3-shortwide/asr-v3-shortwide.dts:39-47`) keeps:
- `reg = <0 0xa0000000 0 0x10000>`;
- `generic-uio`;
- interrupt SPI 89, level-high.

The MMCM is internal to the PL and needs no DT entry. The IRQ meaning changes (§1.5).

### 1.4 Software

| Old | New |
|---|---|
| `software/capture/kv260_voice.py`: one AXI-Lite read per sample, each popping the FIFO; mono, 24-bit, 16 kHz | `sw/audio_ring.py`: `AudioRing(UioWindow("/dev/uioN")).read()` returns `(left, right, lost)` with int16 samples at 16 kHz, copied in one ctypes slice per poll |
| `software/capture/continuous_capture.py` writes 24-bit mono WAV | Use `python3 sw/audio_ring.py --seconds 30 out.wav` (16-bit stereo), or adapt `continuous_capture.py` to call `AudioRing.read()` |
| The frontend got 24-bit samples / 2^23 | Feed `left / 32768.0`. The default gain is +24 dB. The NeMo per-feature normalisation removes absolute level, so this only matters for the log floor **[E]** |
| `kv260_voice.py` MAC bring-up mode | Gone with `qn_mac`. Keep that script in `archive/` |

Also discard the first ~50 ms after enabling. That covers mic wake-up and the DC blocker settling: the time constant is 32 ms, and at +24 dB gain the initial −0.1 FS offset saturates for about 15 ms **[C]**.

### 1.5 Interface changes, old → new

| | `voice_axi` (old) | `audio_capture_axi` (new) |
|---|---|---|
| Sample path | 24-bit mono at 16 kHz, popped from 0x8004 | `{R16, L16}` words at 16 kHz in a ring at 0x8000–0xFFFF |
| Buffer | 1,024 samples = 64 ms **[C]** | 8,192 frames = 512 ms **[C]** (`RING_AW = 13`; 1 s needs `RING_AW = 14` with `ADDR_WIDTH = 17` and a new 128 KB address range) |
| IRQ | count ≥ 160 (10 ms) or overflow | FILL ≥ IRQ_THRESH (default 4,000 = 0.25 s, i.e. one hop) or overrun, when `CTRL.irq_en` = 1 |
| Drop accounting | `dropped` counter in the FIFO | `OVERRUNS` (writer overtook READ_CNT), `CDC_DROPS` (sequence gaps), `SAT_CNT`, sticky STATUS bits |
| Low 32 KB | `qn_mac` registers | Registers 0x00–0x2C (`rtl/audio_capture_axi.v` header) |

---

## 2. How this changes the speedup

**Short answer:** it does **not** change the inference speedup. The shortwide figure of 9.86–12.86 % lower p50 than CPU stays as it is **[M]** (`RESULTS.md`). Those benchmarks time audio that is already in memory, so capture isn't on their timed path.

What the fix changes is whether the live system can run at the hop the latency target needs without dropping audio. It also takes a little load off the PS. The inference speedup only moves with the whole-encoder work (M3/M4), estimated at 148 → 25–45 ms per 2.56 s window **[E]**.

### 2.1 Live pipeline

| Metric | Before | After | Tag |
|---|---|---|---|
| Inference p50 at 1 s (CPU / FPGA) | 105.25 / 92.63 ms | unchanged | **[M]** |
| Reduction vs CPU | 9.86–12.86 % | unchanged (capture is in the PL for both modes, so the comparison stays fair) | **[M]** |
| Mic BCLK | 1.024 MHz, **below the 2.048 MHz minimum** | 3.072 MHz (datasheet typical) | **[M]** datasheet, **[M]** `test_clock_spec` |
| BCLK edge jitter | 2.89 ns RMS (10 ns NCO quantisation / √12) vs a 2 ns limit | MMCM output, ≈ 0.1 ns **[E]**; check the clk_wiz jitter report | **[C]/[E]** |
| Audio buffered before data is lost | 64 ms | 512 ms (8×) | **[C]** |
| Stall it survives, relative to one 2.55 s inference (170 ms CPU, 148 ms FPGA) | 0.38–0.43× | **3.0–3.5×** | **[C]** from **[M]** |
| PS transactions | 16,000 per-sample Python MMIO pops/s, mono | 16,000 32-bit loads/s in ~20 ctypes calls/s (50 ms polls), stereo | **[C]** |
| PS CPU for capture | ~1.6–4.8 % of one A53 (assuming 1–3 µs per Python pop) | ~0.5–1 % (assuming 0.2–0.4 µs per device load plus list conversion) | **[E]**; measure with `time.process_time()` around `read()` |
| Added latency | — | **+1.0 ms**: FIR group delay 47.5 samples at 48 kHz. DC blocker adds ≈ 9 µs at 300 Hz; CDC 30 ns | **[C]** |
| Share of the 0.43 s latency target | — | 0.23 % | **[C]** |
| Hop the target needs (H = 0.25 s) | Not sustainable: a 64 ms buffer can't cover one inference unless the reader has a dedicated real-time core | Sustainable: 512 ms covers two consecutive windows plus margin | **[C]** |

### 2.2 PL cost

| Resource | Before (`voice_axi`) | After (`audio_capture_axi`) | Tag |
|---|---|---|---|
| BRAM36 | 0 (FIFO in LUTRAM) | **+8** (8192 × 32 bits = 256 Kb). Shortwide has 35.5 free **[M]** | **[C]** |
| URAM | 0 | 0 (shortwide URAM is 100 % used **[M]**, so the ring is in BRAM) | — |
| DSP48E2 | inside `qn_mac` (not separated in the flat report) | ~1 for the FIR MAC (18×18 product, 44-bit accumulator) | **[E]** |
| LUT / FF | 1024 × 24 LUTRAM FIFO + `qn_mac` + AXI | ≈ 1.0–1.5 k LUT, 0.8–1.2 k FF (FIR history in LUTRAM, two 40-bit DC blockers, counters) | **[E]** |
| Clocking | none | +1 MMCM | — |
| Timing | WNS +0.055 ns, critical path inside `qn_mac` **[M]** | That path disappears with `qn_mac`; new WNS **[UNVERIFIED]** until built | — |

---

## 3. Review checklist

- [ ] **Sampling phase vs the real board.** The RTL samples DATA 162.8 ns after the BCLK rise. On a scope, measure the actual DATA delay after the BCLK rise at the FPGA pin (datasheet t_DC ≤ ~66 ns) and confirm ≥ 50 ns of margin.
- [ ] **`clk_wiz`:** actual output frequency and jitter; `locked` wired to `aud_locked`.
- [ ] **BD swap** (`bd_patch_audio.tcl`): net names match your open BD, address is still 0xA000_0000 / 64 KB, `validate_bd_design` is clean.
- [ ] **XDC:** each exception matches cells after synthesis; `report_cdc` has no unsafe crossings.
- [ ] **Gain default** of 4 (+24 dB) is sensible for the demo distance. Check `SAT_CNT` after a loud test.
- [ ] **`audio_ring.py` on the board:** no SIGBUS from the ctypes slice on device memory; `time.process_time()` cost per second.
- [ ] **Board tests** (pass criteria in the ROADMAP M1 gate):
  - (a) BCLK 3.072 MHz on a scope;
  - (b) a 1 kHz tone at 0.5 m shows a 1 kHz peak with DC ≈ 0, and a 14 kHz tone is not audible as 2 kHz;
  - (c) tap each mic and the correct channel responds;
  - (d) 30 minutes of capture while the shortwide inference loop runs at H = 0.25 s: `OVERRUNS = 0`, `CDC_DROPS = 0`, `software_lost = 0`.
- [ ] **Recording provenance:** confirm whether `research/eval/user-recording/speech.wav` (mean −0.096 FS) came from this mic. If it did, its DC offset is what the DC blocker targets.

## 4. Not done

- No synthesis, implementation or board run (Vivado is on the PC). Resource and timing figures above are estimates until the first build.
- `continuous_capture.py` is not ported; `audio_ring.py` includes a minimal capture CLI.
- The 1 s ring option (`RING_AW = 14`) needs a 128 KB window at a new base address plus a DTS change. The default 0.512 s avoids both.
