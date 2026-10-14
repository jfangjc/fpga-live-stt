# Mic capture fix: changes, design decisions, test plan and next steps

**Audience:** the teammate integrating and testing this on the KV260.
**Date:** 2026-10-11.

**Status:** RTL is complete and verified in simulation only:
- Verilator `-Wall` lint is clean.
- cocotb: 22/22 pass.
- pytest: 11/11 pass.

**Not yet** synthesised, built or run on the board. Round 1 testing (this document) is the first time it meets hardware.

**Evidence tags:**
- **[M]** measured, with source;
- **[C]** computed;
- **[E]** estimate, assumptions stated;
- **[UNVERIFIED]** not checked yet.

Paths starting `` are relative to the repository root. Everything else is relative to this folder. The wider architecture review and decision log (`ARCHITECTURE_REVIEW.md`, `DECISIONS.md`, `ROADMAP.md`) are sent separately. The decision IDs below (D-xx) match them.

---

## 1. TL;DR

- **What changed:** `audio_capture_axi` replaces `voice_axi`. It sits at the same address (0xA000_0000, 64 KB), on the same pins and the same IRQ.
  - The mic now runs inside its datasheet clock range: 3.072 MHz, previously 1.024 MHz.
  - Both I2S slots are captured.
  - 48 → 16 kHz decimation, DC removal and gain run in the PL.
  - The 64 ms FIFO is replaced by a 512 ms ring buffer.
  - The legacy `qn_mac` tile, which held the design's critical timing path, is gone.
- **What gain to expect:**
  - **Model inference is not faster.** Shortwide stays about 9.9–12.9 % below CPU p50 **[M]**.
  - The gain is in the **live pipeline**: no dropped audio while inference runs, about 8× more buffer, ~1–3 % of a core returned to the PS **[E]**, and +1.0 ms latency **[C]**.
  - This is the prerequisite for running live at a 0.25 s hop, which the ~0.5 s latency target needs.
- **What round 1 has to establish:**
  - (1) It builds and meets timing.
  - (2) The mic is captured correctly at 16 kHz.
  - (3) Zero audio loss for 30 minutes under inference load.
  - (4) No inference regression.
  - (5) Measured reader CPU, old vs new.
  - §7 then decides what to optimise next from those numbers.

---

## 2. What changed

### 2.1 Before and after

| | Before: `voice_axi` + `sph0645_rx` | After: `audio_capture_axi` |
|---|---|---|
| Mic clock | BCLK 1.024 MHz from a 100 MHz NCO (`rtl/sph0645_rx.v:2,15`), **below the 2.048 MHz datasheet minimum**; sleep threshold 0.9 MHz | BCLK **3.072 MHz** = 24.576 MHz ÷ 8 (datasheet typical) |
| Edge jitter | 10 ns quantisation → 2.89 ns RMS **[C]** vs 2 ns allowed | MMCM clock, ≈ 0.1 ns **[E]** |
| Slots | Left only | Left and right (second mic on SEL = 3V3, no new pins) |
| Rate / format | 16 kHz, raw 24-bit mono | 48 kHz capture → 96-tap FIR ÷3 → **16 kHz, 16-bit stereo** `{R16, L16}` |
| DC offset | Passed through (the recording has mean −0.096 FS **[M]**) | DC blocker, ≈ 5 Hz corner, before the gain |
| Gain | None | Programmable shift 0–8 (×6.02 dB), default 4 (+24 dB), saturating, with a counter |
| Buffer | 1,024-entry pop-on-read FIFO = **64 ms** (`voice_axi.v:55`) | 8,192-frame ring = **512 ms**, bulk-readable, write/read counters |
| Loss accounting | `dropped` counter | `OVERRUNS`, `CDC_DROPS`, `SAT_CNT`, sticky STATUS bits, plus software `lost` |
| IRQ | count ≥ 160 samples (10 ms) | FILL ≥ IRQ_THRESH (default 4,000 = one 0.25 s hop) or overrun |
| Extra logic | `qn_mac` bring-up tile (worst routed path, WNS +0.055 ns **[M]**) | Removed |
| PS reader | One Python MMIO pop per sample, 16,000 per second | One ctypes slice per poll (4 per second at a 0.25 s hop) |

### 2.2 Files

| File | Role |
|---|---|
| `rtl/audio_capture_axi.v` | Top level: AXI-Lite slave, register map, ring buffer, CDC, reset/enable synchronisers |
| `rtl/i2s_rx_stereo.v` | I2S master/receiver, both slots, fixed sampling phase |
| `rtl/decim3_fir.v` + `rtl/decim3_coeffs.vh` | 3:1 decimator, one time-shared MAC, 96 taps |
| `rtl/dc_gain.v` | DC blocker, gain, round/saturate to 16-bit |
| `constraints/audio_cdc.xdc` | Replaces `hardware/mic_cdc.xdc` |
| `scripts/bd_patch_audio.tcl` | Block-design swap: adds `clk_wiz`, replaces the `voice` cell, keeps its address |
| `scripts/gen_coeffs.py` | Filter design (pure Python) → RTL include + golden coefficients |
| `sim/*` | cocotb tests, two-mic SPH0645 bus model, AXI-Lite master, bit-exact golden models |
| `sw/audio_ring.py` | PS ring reader + WAV capture CLI (replaces `kv260_voice.py` capture) |
| `sw/bench_capture.py` | **Round 1 benchmark:** losses, reader CPU, read gaps, frame rate, tone and DC under configurable load |
| `docs/INTEGRATION.md` | Step-by-step integration checklist |

---

## 3. Design decisions

Every decision lists what would make us change it, so round 1 can confirm or overturn each one.

### D-12: Mic clocked at 3.072 MHz from an integer-divided audio clock; decimate 3:1 in the PL
- **Why:**
  - The datasheet range is 2.048–4.096 MHz (Knowles SPH0645LM4H-B; Adafruit says "2–4 MHz").
  - The old 1.024 MHz sits just above the 0.9 MHz sleep threshold.
  - The NCO jitter of 2.89 ns RMS **[C]** exceeds the 2 ns TIE spec.
- **Clock:** an MMCM from pl_clk0 (99.999001 MHz). The best setting is D = 1, M = 10.875, O = 44.25 → **24.576026 MHz (+1 ppm)**, VCO 1,087.5 MHz **[C]**.
- **Alternatives rejected:**
  - Keep 1.024 MHz: out of spec.
  - 100 MHz ÷ 32 = 3.125 MHz: fs 48.83 kHz, which leaves a non-integer 3.05:1 ratio to 16 kHz and forces a fractional resampler.
  - 2.048 MHz with ÷2: sits exactly at the minimum.
- **Change it if:** the scope shows the mic misbehaving at 3.072 MHz (unlikely; it's the datasheet test condition), or `clk_wiz` cannot reach ±100 ppm.

### Sampling phase: DATA sampled 162.8 ns after the BCLK rise
- **How:** the RTL samples the pad at the BCLK falling-edge instant (4 audio clocks after the rise) through a two-flop synchroniser.
- **Margin:** the datasheet t_DC is ≤ ~66 ns, so margin is ≈ 90 ns either way **[C]**.
- **Simulation evidence:** capture is exact for t_DC 0–150 ns and fails at 200 ns, which pins the sampling instant **[M sim]** (`test_i2s_rx.py`).
- **Change it if:** the scope shows a real DATA delay above ~110 ns (board or wiring). Move the shift from `ph == 5` to `ph == 6` or `7` in `i2s_rx_stereo.v`, which samples 40.7 or 81.4 ns later. Then update `test_sampling_point_margin`.

### Decimation filter: 96-tap Kaiser (β = 6) low-pass, fc = 8 kHz, Q1.17, sum exactly 2^17
- **Why:** after ÷3, anything that folds into the speech band 0–6.8 kHz comes from 9.2–16 kHz, so the stopband starts there.
- **Measured on the quantised coefficients [C]:**
  - passband ±0.004 dB to 6.8 kHz;
  - ≤ −66.5 dB from 9.2 kHz;
  - −6 dB at 8 kHz;
  - DC gain exactly 1;
  - linear phase.
- **In simulation [M sim]:** 1 kHz −0.03 dB, 12 kHz (aliases to 4 kHz) −91 dB.
- **Cost:**
  - 2 × 96 MACs per output = 3.07 M MAC/s **[C]** on **one** time-shared DSP;
  - 195 cycles per output out of 1,536 available;
  - group delay 0.99 ms **[C]**.
- **Trade-off:** the 7–8 kHz region (the top Citrinet mel bins) is partly attenuated, plus some aliasing from 8–9 kHz. Speech energy there is small and the mic's own bandwidth is 20 Hz–10 kHz.
- **Change it if:** the WER sweep (§7, O2) on audio recorded through this path is worse than on 16 kHz reference audio. A wider passband needs about 128 taps, which is still one DSP.

### DC blocker (K = 9) before the gain; gain shift default 4 (+24 dB); 16-bit output
- **Why the order:** a −0.1 FS DC offset amplified by +24 dB would saturate permanently, so DC has to go first.
- **Corner and settling:** 1 − 2^−9 gives a ≈ 5 Hz corner, τ = 512 samples = 32 ms. The leak term is a shift, so the stage needs no multiplier.
- **Simulation [M sim]:** −0.1 FS DC drops to a 0.375 LSB residual.
- **Why +24 dB:** normal speech at about −55 dBFS raw lands near −31 dBFS. The mic noise floor (−91 dBFS, from the 65 dB(A) SNR) stays well above 16-bit quantisation (−98 dBFS) **[C]**.
- **Startup:** the first ~15 ms after enable saturate while DC decays **[C]**. The reader discards 50 ms.
- **Change it if:** round 1 shows `SAT_CNT > 0` at demo speaking distance (lower the gain to 3), or the noise floor is quantisation-limited (raise it).

### CDC: two-phase toggle handshake with a 2-bit sequence number
- **Why:**
  - At 16 kHz the payload is stable for 62.5 µs, against a 3-cycle (30 ns) synchroniser, so a toggle plus held data is the simplest robust crossing.
  - The sequence number lets the destination count any lost transfer (`CDC_DROPS`, expected 0).
  - No XPM FIFO is needed, so it simulates directly in Verilator.
  - The CDC source is reset only by the global reset, so toggling `enable` cannot fake an edge.
- **Change it if:** `CDC_DROPS ≠ 0` ever appears. That would indicate a constraint or clocking error, not a design limit.

### D-14: Ring buffer of 8,192 frames (0.512 s) in BRAM, inside the existing 64 KB window
- **Why:**
  - It is 3.0× the longest measured inference: 169.5 ms for a 2.55 s CPU window, 147.7 ms on shortwide **[M]**.
  - It fits **8 BRAM36** (shortwide has 35.5 free **[M]**). URAM is 100 % used on shortwide **[M]**.
  - Keeping the 64 KB window means **no device-tree or address-map change**.
  - The old FIFO (64 ms) is shorter than one inference.
- **Change it if:** round 1 shows the maximum gap between reads above ~250 ms under real load (headroom < 2×). Then go to 1 s (`RING_AW = 14`, `ADDR_WIDTH = 17`, a 128 KB window at a new base address, DTS change).

### D-13: One mic for ASR; second mic optional (DOA later)
- **Why:** a 2-mic delay-and-sum at ≤ 100 mm gives only 0.3–2.8 dB in diffuse noise **[C]**. Halving the talker's distance gives 6 dB **[C]**. Capturing the second slot costs ~30 LUT/FF **[E]**.
- **Change it if:** a 2-mic recording of the demo room shows ≥ 2 pp WER gain with beamforming.

### D-17: Remove `qn_mac`
- **Why:** it is a bring-up tile used only by `kv260_voice.py`, and it holds the worst routed path: 22 logic levels, 9.479 ns, WNS +0.055 ns **[M]** (`reports/fused/short_wide_system_timing.rpt`).
- **Change it if:** someone still needs the MAC bring-up harness. Keep it in an archive branch.

### Register map and IRQ semantics
- **Layout:** registers at +0x00–0x2C; the ring is read-only at +0x8000.
- **READ_CNT is software-owned:** the PS publishes how far it has read, so the hardware can count true overruns.
- **IRQ threshold defaults to one hop (4,000 frames).** A reader can sleep on the UIO IRQ instead of polling (§7, O7).

### Verification approach
- **Golden models are pure-Python integers:** exact at any width, and Python `>>` floors like Verilog `>>>`. This needs no numpy.
- **The two-mic bus model** implements the datasheet's SELECT/tri-state behaviour and counts bus contention.
- **The end-to-end test** compares 50 ring words bit for bit against the golden pipeline applied to exactly the samples the mic models sent.

---

## 4. Expected results (the "prediction" column for round 1)

| Metric | Before | Predicted after | Basis |
|---|---|---|---|
| Inference p50, 1 s context, FPGA | 92.63 ms | **same** (±1 %) | **[M]** `reports/fused/shortwide_scheduled_summary.json`; capture isn't in the timed path |
| Reduction vs CPU (0.5 / 1 / 2.55 s) | 9.86 / 11.99 / 12.86 % | **same** | **[M]** |
| BCLK / WS | 1.024 MHz / 16 kHz | **3.072 MHz / 48.000 kHz** | **[M sim]** |
| Frame rate into the ring | — | **16,000 Hz ± 100 ppm** | **[C]** MMCM +1 ppm plus board-oscillator tolerance **[E]** |
| Buffer before loss | 64 ms | **512 ms** | **[C]** |
| Loss in 30 min under inference load | not tested (likely > 0, because 64 ms < 148 ms) | **0** | **[C]**/**[E]** |
| Reader CPU, % of one A53 | ~1.6–4.8 % | **~0.5–1 %** | **[E]**: assumes 1–3 µs per Python pop vs 0.2–0.4 µs per 32-bit device load |
| Added latency | — | **+1.0 ms** (0.23 % of a 0.43 s target) | **[C]** |
| Routed WNS | +0.055 ns | **higher** (old critical path removed) | **[UNVERIFIED]** |
| BRAM36 | 108.5 | **≈ 116.5** (+8) | **[C]** |
| DSP | 866 | ≈ 866 − (`qn_mac` DSPs) + 1 | **[E]** |
| Quiet-room noise floor at gain 4 | — | about −65 to −50 dBFS (room noise dominates; the mic alone is −67 dBFS) | **[E]** |

---

## 5. Test plan, round 1

Run the stages in order. Each one has a pass criterion; record the measured value in §6.

**Safety (from Henry's setup notes):** never touch 0xA00x_xxxx unless the overlay is loaded *with clocks on*. An unanswered AXI access freezes the board until power-cycled.

### T0: Simulation (5 minutes; macOS, Linux or WSL)

Needs Verilator ≥ 5.036, cocotb 2.1 and pytest. Run these from this folder:

```bash
make
```

```bash
make bench-dry
```

- **Pass:**
  - `lint: clean`;
  - `6 passed`, `5 passed`;
  - `dc_gain 6/6`, `decim3 4/4`, `i2s_rx 8/8`, `top 4/4`;
  - `bench-dry` exits 0.
- **Waves:** `make sim DUT=top WAVES=1`, then `make waves DUT=top` (Surfer).

### T1: Vivado build (Vivado 2026.1, the snapshot's shortwide project)

1. Add the four `rtl/*.v` files plus `rtl/decim3_coeffs.vh` (Verilog header; add `rtl/` to the include dirs). Remove `voice_axi.v`, `sph0645_rx.v` and `qn_mac.v`.
2. With the BD open, run `source mic-capture-fix/scripts/bd_patch_audio.tcl`. Check that `CLKOUT1_ACTUAL_FREQ` is 24.576 MHz.
3. Swap `hardware/mic_cdc.xdc` for `constraints/audio_cdc.xdc`.
4. Synthesise and implement with the usual shortwide scripts (`scripts/short_wide_synth.tcl`, `short_wide_implement.tcl`). **[UNVERIFIED]** how these interact with the patched BD; you know this flow best.
5. Write the reports:

```tcl
report_timing_summary -file reports/audio_timing.rpt
report_clock_interaction -file reports/audio_clock_interaction.rpt
report_cdc -details -file reports/audio_cdc.rpt
report_utilization -hierarchical -file reports/audio_util_hier.rpt
report_drc -file reports/audio_drc.rpt
```

- **Pass:**
  - setup and hold slack ≥ 0 on both clocks;
  - `report_cdc` has no unsafe/unknown crossings;
  - every XDC exception matched at least one object (no "no valid object" warnings);
  - DRC has no errors;
  - BRAM ≈ +8.
- **Record:**
  - WNS/WHS vs the old +0.055 / +0.011 ns;
  - the new critical path;
  - the `voice` cell's LUT/FF/DSP/BRAM;
  - total utilisation.

### T2: Package and bring up on the board

1. **Package** a new app, `asr-v3-shortwide-audio`. Run `bootgen -arch zynqmp -image boot.bif -process_bitstream bin` as in `README.md`. Copy `asr-v3-shortwide.dtbo` and `shell.json` **unchanged**: the address and IRQ are identical. Keep `asr-v3-shortwide` installed for rollback.
2. **Activate** with a copy of `deployment/asr-v3-shortwide/activate.sh` that loads `asr-v3-shortwide-audio`. The clock node name inside the reused dtbo stays `asr-v3-shortwide-clock` **[UNVERIFIED]**. `qn_tile.ko` is unchanged.
3. **Identity gates:** the snapshot's install and benchmark scripts pin firmware SHA256 (`install_short_wide_firmware.sh`, `shortwide_firmware_evidence.json`). Create a new evidence file for the audio bitstream with the same prepare/bind scripts (`scripts/prepare_short_wide_firmware.py`, `scripts/bind_short_wide_binary.py`) pointed at the new app **[UNVERIFIED options]**. A hash refusal means the gate is working.
4. **Find the device and read the ID registers:**

```bash
grep -H . /sys/class/uio/uio*/name
```

```bash
sudo python3 -c "import sys; sys.path.insert(0,'sw'); from audio_ring import *; d=UioWindow('/dev/uio4'); print(hex(d.read32(ID)), hex(d.read32(PARAMS)), d.read32(DEPTH))"
```

Replace `/dev/uio4` with the device whose name is `voice-prototype`.

- **Pass:** `0x41554431 0x60030901 8192`.
- **Scope:**
  - BCLK (D11 / PMOD pin 6) = 3.072 MHz;
  - WS (B10 / pin 2) = 48.000 kHz;
  - DATA (E12 / pin 4) transition delay after the BCLK rise.
  - **Pass:** 162.8 ns − measured delay ≥ 50 ns.

### T3: Signal quality

```bash
sudo python3 sw/bench_capture.py --seconds 60 --tone-hz 1000 --out t3_silence.json
```

```bash
sudo python3 sw/bench_capture.py --seconds 60 --tone-hz 1000 --out t3_tone1k.json
```

```bash
sudo python3 sw/audio_ring.py --seconds 10 t3_speech.wav
```

- **Procedure:** the first run is in a quiet room. For the second, play a 1 kHz tone from a phone at ~0.5 m. For the third, speak at demo distance, then listen on a laptop.
- **Pass:**
  - `hw_frame_rate_hz` = 16,000 ± 2 Hz;
  - `left.tone_dbfs` in the tone run is ≥ 30 dB above the silence run;
  - `|left.dc_lsb| < 20` (below −64 dBFS);
  - `saturated_samples = 0` for normal speech;
  - tapping each mic moves the correct channel (left = SEL GND).
- **Record:** noise floor (`left.rms_dbfs` in the silence run), tone level, DC, saturation count.

### T4: Robustness under load (the main performance result)

```bash
sudo python3 sw/bench_capture.py --seconds 1800 --hop-ms 250 --load-ms 170 --out t4_spin170_30min.json
```

```bash
sudo python3 sw/bench_capture.py --seconds 300 --hop-ms 250 --load-ms 250 --out t4_spin_full.json
```

```bash
sudo python3 sw/bench_capture.py --seconds 120 --hop-ms 700 --out t4_expect_loss.json
```

- **What each run does:**
  - **First:** emulates CPU-only inference at H = 0.25 s (4 workers × 170 ms busy per 250 ms) for 30 minutes.
  - **Second:** all four cores saturated.
  - **Third:** a negative control. Reading every 700 ms exceeds the 512 ms ring, so it **must** report losses and exit 1.
- **Real-load run:** run `bench_capture.py --seconds 600 --hop-ms 250` (no `--load-ms`) while the shortwide inference loop runs in another shell, e.g. `software/latency/confirm_short_wide_schedule.py --contexts 1 --runs 2000`.
- **Pass:**
  - the first, second and real-load runs report `software_lost = hw_overruns = cdc_drops = 0` (exit 0);
  - the negative control reports losses, which proves the accounting works on hardware.
- **Record:** `gap_between_reads_ms.max` and `ring_headroom_x` (expect ≥ 2 at a 250 ms hop).

### T5: Reader CPU, old vs new

- **New:** read `reader_cpu_percent_of_one_core` from the T4 runs (with and without load).
- **Old (old firmware `asr-v3-shortwide`), same load:**

```bash
python3 sw/bench_capture.py --load-only --seconds 60 --hop-ms 250 --load-ms 170 --out load.json &
```

```bash
sudo /usr/bin/time -v .venv/bin/python software/capture/continuous_capture.py --device /dev/uioN --seconds 60 --chunk-seconds 10 --output old_capture
```

- **Old CPU %** = (user + sys) / 60 s × 100. Also record the old FIFO's `dropped` counter from its report.
- **Pass:** new < old. Prediction: new ~0.5–1 %, old ~1.6–4.8 % **[E]**, with old drops > 0 under load **[E]**.
- **Note:** `continuous_capture.py` also writes WAV files. For parity, compare against a new run that also writes WAV:

```bash
sudo python3 sw/audio_ring.py --seconds 60 x.wav
```

  Run it under `/usr/bin/time -v` in the same way.

### T6: Inference regression on the new bitstream

```bash
.venv/bin/python software/ort_fpga_shortwide/smoke.py --physical --out reports/fused/audio_physical_synthetic.json
```

```bash
.venv/bin/python software/ort_fpga_shortwide/validate.py --physical --out reports/fused/audio_physical_validation.json
```

```bash
.venv/bin/python software/latency/confirm_short_wide_schedule.py --contexts 1 --runs 300 --out reports/fused/audio_scheduled_one.json
```

- **Pass:**
  - 240 arithmetic and 36 prefix-parity checks as before;
  - 1 s FPGA p50 within ±1 % of 92.63 ms;
  - the reduction vs CPU is still positive with a CI above zero.
- **T6b:** repeat the 300-pair confirmation **while** `bench_capture.py --seconds 900 --hop-ms 250` runs. This is the live condition. Capture runs in both the CPU and FPGA arms, so the comparison stays fair.
- **Record:** the p50 change caused by concurrent capture.

---

## 6. Results sheet (fill in and send back)

| Test | Metric | Predicted | Measured | Pass? |
|---|---|---|---|---|
| T0 | lint / pytest / cocotb | clean / 11 / 22 | | |
| T1 | WNS / WHS (ns) | > +0.055 / ≥ 0 | | |
| T1 | new critical path | outside `voice` | | |
| T1 | `voice` LUT / FF / DSP / BRAM | ~1.0–1.5 k / ~1 k / ~1 / 8 | | |
| T1 | report_cdc unsafe | 0 | | |
| T2 | ID / PARAMS / DEPTH | 0x41554431 / 0x60030901 / 8192 | | |
| T2 | BCLK / WS (scope) | 3.072 MHz / 48.000 kHz | | |
| T2 | DATA delay after BCLK rise; margin | ≤ 66 ns; ≥ 50 ns | | |
| T3 | frame rate (Hz) | 16,000 ± 2 | | |
| T3 | noise floor (dBFS, gain 4) | −65 to −50 | | |
| T3 | 1 kHz tone over silence (dB) | ≥ 30 | | |
| T3 | DC (LSB) | < 20 | | |
| T3 | L/R mapping, saturation at speech | correct, 0 | | |
| T4 | 30 min at 170 ms load: lost / overruns / cdc | 0 / 0 / 0 | | |
| T4 | full load, 5 min: lost / overruns / cdc | 0 / 0 / 0 | | |
| T4 | real inference load: lost / overruns / cdc | 0 / 0 / 0 | | |
| T4 | max read gap (ms) / headroom (×) | ~250–260 / ≥ 2 | | |
| T4 | negative control (700 ms hop) reports loss | yes | | |
| T5 | reader CPU new (% of one core) | 0.5–1 | | |
| T5 | reader CPU old; old drops | 1.6–4.8; > 0 | | |
| T6 | arithmetic / prefix parity | 240 / 36 | | |
| T6 | FPGA p50 at 1 s (ms) | 92.6 ± 1 % | | |
| T6b | p50 change with capture running | < 1 % | | |

**Send back:**
- this table;
- all `t*.json` files;
- the five `reports/audio_*.rpt` files;
- scope screenshots;
- `t3_speech.wav`.

---

## 7. After round 1: how to read the results and what to optimise next

### 7.1 If something fails

| Symptom | Likely cause | Action |
|---|---|---|
| Board hangs on the ID read | Overlay or clocks not loaded, or the address map changed | Power-cycle. Confirm `xmutil` loaded the audio app and `fpga_manager` reads `operating` before any MMIO |
| No BCLK | `clk_wiz` not locked (`aud_locked` = 0), or `enable` not set | Check `locked` in the BD/ILA; `CTRL` bit 0 |
| BCLK fine, samples all 0 | DATA pin or SEL wiring; the mic sees no WS edge | Scope DATA. Mic #1 SEL must be GND |
| Samples noisy or ±1-bit garbage | Sampling phase too early for the real t_DC | Move the shift to `ph == 6` or `7` in `i2s_rx_stereo.v` (§3) and re-run T0 |
| L and R swapped | SEL wiring or WS polarity | SEL = GND must appear on the **left** (low 16 bits) |
| Frame rate off > 200 ppm | `clk_wiz` output frequency | Read `CLKOUT1_ACTUAL_FREQ`; set M/D/O to 10.875/1/44.25 manually |
| `SAT_CNT` > 0 at normal speech | Gain too high for that distance | `--gain-shift 3` (−6 dB) |
| Losses under the spin load | Reader starved | See O6 below |
| `CDC_DROPS` > 0 | Constraint or clocking error (should be impossible by design) | Check `report_cdc`, the `pay_src → pay_cap` max-delay exception, and clock interaction |
| Inference p50 regressed > 1 % | Placement change, or capture competing for inference cores or the IRQ core | Compare timing reports; pin the reader to a core not used by ORT workers; move SPI 89 affinity |

### 7.2 Next optimisations, ordered by expected gain

Each item says which round 1 number decides it.

| # | Optimisation | Expected gain | Decided by these round 1 results | Cost |
|---|---|---|---|---|
| O1 | **Live sliding-window loop on shortwide** (M1): `AudioRing` → 2.56 s window → resident API → stitched tokens, first at H = 0.5 s, then 0.25 s | Live text for the first time. Mean latency 0.92 s at H = 0.5, R = 0.5; **0.54 s** at H = 0.25, R = 0.25 **[C]**. PS duty 30 % → 59 % **[C]** | T4 zero loss under real load (prerequisite); T6b no regression | Low (software only) |
| O2 | **Streaming accuracy sweep**: WER vs right context R ∈ {0, 0.25, 0.5, 1.0} s and H ∈ {0.25, 0.5} s, on LibriSpeech dev plus **≥ 50 utterances recorded through this new path** (`audio_ring.py`) | Picks R and H with data. The R choice is worth 0.25 s of latency per step **[C]** | T3 audio quality (the new filter, DC and gain are now part of the frontend) | Low (CPU only, Mac or PC) |
| O3 | **Display**: DRM/KMS text at 1080p60, GNOME off (D-16) | Text on the monitor; ≤ 8 ms mean display wait **[C]**; ≤ 0.6 % of a core **[E]** | T6b CPU headroom | Low |
| O4 | **Whole Citrinet block on the PL** (M3), then **the whole encoder** (M4): activations on chip, weights streamed, one DMA program per window (D-06 to D-10). **This is the actual speedup** | Per window **148 → ~25–45 ms** **[E]**; reduction vs CPU **12 % → ~75–85 %** **[E]**; MAC share on the PL 43.5 % → ≥ 99.9 % **[C]**; PS duty at H = 0.25 59 % → ~10 % **[E]**; mean latency 0.54 → **0.43 s** **[C]** | T1 WNS and new critical path (headroom for the sequencer); T1 BRAM/URAM after this change (where the activation banks go); T6 baseline numbers | High |
| O5 | **PL frontend** (window, FFT-512, mel-80, log, normalisation) fed directly by the decimator | Saves ≤ 6 ms of PS per window (measured frontend 6.09 ms at 1 s context **[M]**). Audio never touches the PS | Only worthwhile once O4 makes the remaining PS time significant. T3 noise and level stats inform the fixed-point ranges | Medium |
| O6 | **Capture-path upgrades** (only if round 1 asks for them) | — | **If T4 headroom < 2× or losses appear:** (a) run the reader with `SCHED_FIFO` on a core without ORT workers; (b) sleep on the UIO IRQ (threshold = hop) instead of polling; (c) 1 s ring (`RING_AW = 14`, 128 KB window, DTS change). **If T5 reader CPU > 2 %:** a small C copy helper via ctypes, or audio S2MM DMA to DDR | Low to medium |
| O7 | **IRQ-driven reader** (wake exactly when one hop is buffered) | Removes polling jitter and frees the reader core between hops | T4 gap distribution | Low |
| O8 | **Second mic and DOA** (GCC-PHAT) | Demo feature: speaker direction on screen, ~4° at 100 mm **[C]**. **Note:** DOA needs the **48 kHz** pre-decimation samples (0.93 samples of maximum delay at 16 kHz with 20 mm spacing **[C]**), so add a 48 kHz side path or compute GCC-PHAT in the PL | T3 L/R correctness; mic spacing on the bench | Medium |
| O9 | **DSP pipelining and clock**: only if O4's counters show compute-bound stalls | Clock headroom; today's DRC flags 1,396 DSP input-pipelining warnings **[M]** | T1 timing after this change; O4 counters | Medium |

### 7.3 What to keep in mind for later rounds

- **Fair comparisons.** Capture now runs in the PL for both the CPU and FPGA arms, so keep it running in both during live benchmarks (T6b style). Never compare an FPGA arm with capture against a CPU arm without it.
- **The frontend changed.** The capture filter, DC blocker and gain are now part of the audio path. Any WER claim must use audio recorded through this path (O2), not only the old WAV files.
- **Identity binding.** Keep the snapshot's practice of binding firmware, driver and model hashes to every result. The new bitstream needs its own evidence file (T2 step 3).
- **Rollback.** Keep `asr-v3-shortwide` installed. A failed audio app must never leave the board without a known-good overlay.
- **Margins to re-check whenever the clock or wiring changes:** the sampling margin (T2 scope) and ring headroom (T4).
- **Numbers to carry into O4 planning:**
  - T1: WNS, BRAM/URAM, `voice` cell size;
  - T6: inference baseline;
  - T4: reader core usage, which decides which core the PS-side SE mailbox (D-10) can use.
