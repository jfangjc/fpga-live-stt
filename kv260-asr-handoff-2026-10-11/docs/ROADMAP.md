# Roadmap to demo day

The demo date is **[UNVERIFIED]**. This plan assumes about seven weeks from 2026-10-11 (UNSW 26T3, week 10). Each milestone ends in a gate. Don't start the next hardware milestone until the gate passes. Decision IDs refer to [DECISIONS.md](DECISIONS.md).

Verification follows Henry's setup notes:
- Verilog RTL;
- Verilator + cocotb 2.1, bit-accurate against numpy golden models (the snapshot's `software/fused/oracle.py` is the golden model for accelerator arithmetic);
- FST waves in Surfer;
- xsim sign-off for anything that instantiates XPM/DSP48E2 (D-18);
- physical runs keep the snapshot's paired-randomised evidence standard.

```
week      1      2      3      4      5      6      7
M0  ████                                              platform + repo freeze
M2  ███████████                                       streaming accuracy study (Mac only, parallel)
M1  ███████████████████                               live MVP on shortwide (demo-safe fallback)
M3                ████████████████                    one full Citrinet block on the PL
M4                              ███████████████████   whole encoder + live integration
M5                                   ░░░░░░░░░░░░░░░  stretch (only if M4 is on track)
```

---

## M0: Platform and repository freeze (week 1)

**Covers:** D-01, D-17 (prep), D-19.

- Install Vivado/Vitis 2026.1 on the PC alongside 2025.2. Add `VIVADO ?=` to the Makefiles.
- Flash a second microSD with the Ubuntu 24.04 Kria image matching kernel `6.8.0-1015-xilinx`. Install the snapshot's cp312 wheelhouse and the `qn_tile` module (`deployment/README.md`).
- `git init` the tree. Move the variants to `archive/` (`deployment/experimental-*` except shortwide, `software/ort_fpga_*` except shortwide, and `rtl/experimental/qn_*_axis` except shortwide and its core). Add `make lint` (Verilator `-Wall`).

**Gate:**
- [ ] The shortwide rebuild on your PC meets timing (WNS ≥ 0, no DRC errors).
- [ ] The 240 physical arithmetic cases and the 36 prefix-parity cases pass on your board (`scripts/run_short_wide_physical.sh`).
- [ ] `make lint` runs on the Mac.

## M1: Live MVP on the existing shortwide accelerator (weeks 1–3)

**Covers:** D-12, D-13 (both slots only), D-14, D-16, D-04 at H = 0.5 s, D-21.

- **RTL:**
  - `i2s_rx` for both slots at BCLK 3.072 MHz from an integer audio clock;
  - XPM async FIFO into the 100 MHz domain;
  - 3:1 polyphase decimator with DC-blocking high-pass;
  - 1 s × 2-channel ring buffer (2 URAM) with a write-pointer register.
  - Remove `qn_mac` from `voice_axi` (D-17).
- **PS:**
  - capture reader (mmap + memcpy);
  - sliding-window driver around the existing resident API (W = 2.56 s, H = 0.5 s);
  - token stitching;
  - DRM/KMS text renderer.
- **Verification:**
  - cocotb: an SPH0645 bus-functional model (SELECT high/low, 18-bit data, tri-state) checks every captured sample. The decimator matches a numpy integer golden model bit for bit. Ring-buffer wrap and overwrite counter are tested.
  - xsim: the async FIFO and URAM wrappers.
  - Board:
    - 1 kHz tone → 16 kHz WAV, checking frequency and SNR;
    - 30-minute capture while inference runs: zero overwritten samples;
    - word-end → pixel latency histogram;
    - render time per update.

**Gate (demo-safe fallback secured):**
- [ ] 10 minutes live with zero dropped samples.
- [ ] p95 latency ≤ 1.2 s.
- [ ] Transcript visible on DP.
- [ ] Routed WNS at or above today's +0.055 ns, and better than the pre-removal build.

## M2: Streaming accuracy study (weeks 1–2, Mac only, parallel with M0/M1)

**Covers:** D-04, D-05, D-08 (accuracy gate).

- Sweep the CPU ORT INT8 model and the integer oracle:
  - R ∈ {0, 0.25, 0.5, 1.0} s;
  - H ∈ {0.25, 0.5} s;
  - per-window vs running normalisation;
  - on 200 LibriSpeech dev-clean + dev-other utterances, the 9 local clips, and ≥ 50 utterances you record on the KV260 mic after M1.

**Gate:**
- [ ] Choose R, H and normalisation. The smallest R within 1 pp WER of full-utterance decoding wins.
- [ ] Integer oracle within 1 pp of FP32 at that operating point.
- [ ] Record the numbers in D-04/D-05 and change their status.

## M3: One full Citrinet block on the PL from a DDR program (weeks 3–5)

**Covers:** D-06, D-07, D-08, D-09, D-10, D-11, D-18.

- **RTL:**
  - descriptor sequencer and stream demux;
  - weight double buffer;
  - four activation banks;
  - depthwise engine extended to a k ≤ 41 parameter;
  - residual Q16 add + ReLU;
  - SE reduce → mailbox IRQ → gate scale;
  - counters (MAC-issue, weight-starved, input-starved, output-blocked, mailbox-wait).
- **Driver:**
  - persistent coherent program buffer;
  - `QN_RUN_PROGRAM` ioctl submitting one SG chain;
  - SE mailbox wait.
- **Target block:** encoder block 2 (k = 13, 5 repeats, stride 1). It is representative and avoids stride-2 in the first iteration.
- **Verification:**
  - cocotb bit-exact against `oracle.py` for block 2 on 36 captured inputs, plus random tensors, with a PS-mailbox model in Python;
  - backpressure, reset and malformed-descriptor tests (port the snapshot's error cases);
  - xsim sign-off with real XPM;
  - board: physical vs oracle logits exact; paired block timing vs that block's optimised CPU subgraph at 2.56 s, all transfers included.

**Gate:**
- [ ] Bit-exact on the board.
- [ ] Block time ≤ ⅓ of CPU block time.
- [ ] Projected whole-window PL time ≤ 50 ms.
- [ ] Otherwise stop and re-plan, and demo the M1 fallback.

## M4: Whole encoder and live integration (weeks 5–7)

**Covers:** D-06 in full, D-20.

- **RTL:** stride-2 depthwise and residual (blocks 1, 7, 14); C up to 640 (block 22 and the decoder conv); a full 24-entry program.
- **PS:** swap the shortwide graph for `QN_RUN_PROGRAM` in the live pipeline; move to H = 0.25 s if M2 allows.
- **Verification:**
  - cocotb per layer type (every kernel size 5–41, stride 2, 80→256, 256→640, 640→257);
  - full-window bit-exact against `oracle.py` on the M2 corpus subset.
- **Board:**
  - full-window logits parity;
  - paired CPU (ORT INT8 best policy) vs PL per-window latency at 2.56 s;
  - PL busy fraction and MAC share from counters;
  - live latency histogram;
  - 30-minute zero-drop run;
  - WER on the M2 set.

**Gate (final acceptance):**
- [ ] Per-window latency ≥ 3× better than CPU.
- [ ] Live mean ≤ 0.5 s / p95 ≤ 0.8 s (or the D-05 revised target).
- [ ] Zero drops in 30 minutes.
- [ ] WER within 1 pp of the CPU at the same operating point.
- [ ] ≥ 50 % of one core idle.

## M5: Stretch goals (only after M4 is on track)

| Item | Decision | Verification |
|---|---|---|
| PL frontend (window, FFT-512, mel-80, log, normalisation) writing UINT8 features directly into the encoder's feature bank | D-15 | cocotb against a numpy fixed-point model; WER delta ≤ 0.5 pp vs the PS frontend |
| SE MLP + sigmoid LUT in the PL (removes the mailbox) | D-10 phase 2 | Bit-exact vs a numpy LUT model; WER delta |
| Second mic + GCC-PHAT DOA arrow on screen | D-13 | Known-angle source at 0/±30/±60°, error ≤ 10° |
| PL text-mode controller into DPSUB live video | D-16 | Frame capture of a test pattern; zero PS render time |

---

## First three concrete tasks

The three can run in parallel.

1. **Freeze the platform (M0, D-01).**
   - Install Vivado 2026.1 on the PC and flash the 24.04 Kria card.
   - On the board, check `uname -r` = `6.8.0-1015-xilinx`.
   - Rebuild shortwide with the snapshot's `scripts/short_wide_synth.tcl` and `short_wide_implement.tcl`, wrapped in a `make bit DESIGN=shortwide` target over SSH.
   - Diff the routed timing summary against `reports/fused/short_wide_system_timing.rpt`.
   - Run the physical validation script on your board.
   - *Done when* timing closes and the 240 + 36 physical checks pass.
2. **Run the streaming-accuracy sweep on the Mac (M2, D-04).**
   - Get the exported INT8 ONNX model and vocabulary. They are not in this snapshot: copy them from the `FPGA-ASR-7pct-verified-2026-10-11` package or re-export the pinned HF checkpoint with `software/model-tools/`.
   - Write `tools/stream_sweep.py`, reusing the snapshot's frontend and WordPiece decoder from `software/runtime/`.
   - Run the R × H × normalisation grid on 200 LibriSpeech dev utterances plus the 9 local clips.
   - *Done when* a WER table exists and D-04's R and H are filled in.
3. **Fix microphone capture in RTL with cocotb tests (M1, D-12, D-14).**
   - **Status 2026-10-11: RTL and simulation done** in [`mic-capture-fix/`](../mic-capture-fix/README.md): lint clean, 22/22 cocotb tests, 11/11 pytest checks. Next: Vivado integration and board tests ([INTEGRATION.md](../mic-capture-fix/docs/INTEGRATION.md) §1, §3).
   - Write `rtl/audio/i2s_rx.v` (both slots, BCLK 3.072 MHz from a 24.576 MHz enable), `rtl/audio/decim3.v` (48-tap polyphase FIR plus DC blocker, coefficients from a numpy windowed-sinc script, no scipy needed) and `rtl/audio/audio_ring.v`.
   - Write `sim/test_audio.py` with a two-SPH0645 bus-functional model and numpy integer golden models.
   - *Done when* `make sim DESIGN=audio` passes, `make lint` is clean, and the waveform shows correct left/right slot capture.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Short right context hurts Citrinet WER too much | Medium | High | M2 measures it first. Fallback options: R = 0.5 s (0.68 s mean latency), running normalisation, lexicon decoding (D-21) |
| The M3 block engine slips | Medium | High | M1 is the demo-safe fallback and still runs 43.5 % of MACs on the PL |
| Vivado 2026.1 install or K26 licensing on your PC **[UNVERIFIED]** | Low | Medium | Build on the snapshot's original machine in the meantime |
| DP not driven with the overlay loaded **[UNVERIFIED]** | Low | Medium | Check in M0 with `modetest`. HDMI is **not** an independent fallback: it carries the same PS DisplayPort output through the carrier's STDP4320 demux ([AMD Smart Camera docs](https://xilinx.github.io/kria-apps-docs/kv260/2022.1/build/html/docs/smartcamera/docs/introduction.html)), so either connector works once the DPSUB works. Connect the monitor before power-on (known resolution-detection issue). Use SSH X-forwarding for development only |
| Board freezes during new-AXI bring-up | Medium | Medium | Keep the snapshot's restoration scripts. Never touch PL addresses without the overlay and clocks loaded. Keep the 5 s DMA timeout and error GPIO |
