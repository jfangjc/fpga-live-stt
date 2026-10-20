# Design decision log

Architecture decision records for the KV260 live speech-to-text project. Evidence tags follow [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md):
- **[M]** measured, with a file or source;
- **[C]** computed, see [`analysis/`](analysis/README.md);
- **[E]** estimated;
- **[UNVERIFIED]** not checked.

**Status meanings:**
- **accepted**: forced by a hard constraint or datasheet. You can still overrule it.
- **proposed**: this review's recommendation, awaiting your sign-off or implementation.
- **needs-measurement**: the decision depends on a number nobody has measured yet.

| ID | Decision | Status |
|---|---|---|
| D-01 | Standardise on the snapshot's platform (Vivado 2026.1, Ubuntu 24.04, kernel 6.8.0-1015-xilinx) | proposed |
| D-02 | Open-vocabulary English, not keyword spotting | proposed |
| D-03 | Keep Citrinet-256-LS | proposed |
| D-04 | Buffered sliding-window inference, W = 2.56 s, H = 0.25 s, R ≥ 0.25 s | needs-measurement |
| D-05 | Latency target: final text mean ≤ 0.5 s, p95 ≤ 0.8 s; zero drops | needs-measurement |
| D-06 | Whole encoder per window on the PL | proposed |
| D-07 | Static descriptor program + one SG-DMA ioctl per window | proposed |
| D-08 | Keep the validated INT8 contract; INT8 between layers, INT8 logits out | proposed |
| D-09 | Activations resident on chip; weights streamed per block, double-buffered | proposed |
| D-10 | SE: PL reduction + PS mailbox (phase 1), PL MLP later | proposed |
| D-11 | Keep 512 PW MACs, 64 DW lanes, 100 MHz; no MAC increase | proposed |
| D-12 | Mic at BCLK 3.072 MHz / 48 kHz from an integer clock, 3:1 decimation in the PL | accepted |
| D-13 | One mic for ASR; capture both slots; second mic only for DOA (stretch) | proposed |
| D-14 | Audio ring buffer in the PL (0.512 s now, 1 s option) instead of a 64 ms pop-FIFO | accepted |
| D-15 | Frontend on the PS for the MVP; PL frontend as stretch | proposed |
| D-16 | Display via DRM/KMS dumb buffer, GNOME off; PL live video as stretch | proposed |
| D-17 | Remove legacy `qn_mac` from `voice_axi`; pipeline DSPs in new RTL | proposed |
| D-18 | Verilator + cocotb verification with behavioural XPM/DSP wrappers; xsim for sign-off | proposed |
| D-19 | Consolidate variants into one tree under git | proposed |
| D-20 | CPU baseline: same model and windows, best ORT INT8 config, NEON C reference for the report | proposed |
| D-21 | Fallbacks: shortwide at H = 0.5 s for the demo; lexicon-constrained CTC for accuracy | proposed |

---

### D-01 Standardise on the snapshot's platform
- **Decision:** Build with Vivado/Vitis 2026.1 and board part `kv260_som:part0:2.0`. Run on Ubuntu 24.04 Kria, kernel `6.8.0-1015-xilinx`, Python 3.12, on a **second microSD**. Keep the 22.04/PYNQ card for the course labs.
- **Context:** The snapshot was built and validated on that stack. Your PC has Vivado 2025.2 with board files 1.2–1.4, and your board runs 22.04 on kernel 5.15.
- **Options considered:**
  - (a) Standardise on 2026.1 / 24.04.
  - (b) Back-port to 2025.2 / 22.04.
  - (c) Keep building on the snapshot's original machine.
- **Deciding numbers:**
  - `scripts/asr_v2_recreate.tcl:23-32` exits with an error on any Vivado other than 2026.1 **[M]**.
  - `numpy==2.5.3` and `onnxruntime==1.30.0` (`software/requirements-runtime.txt`) **[M]**. NumPy ≥ 2.3 requires Python ≥ 3.11, and 22.04 ships 3.10 **[E/UNVERIFIED]**.
  - The driver checks `uname -r` = 6.8.0-1015-xilinx (`deployment/README.md`) **[M]**.
  - Back-porting means editing the BD Tcl and re-qualifying IP versions, rebuilding wheels, and recompiling and re-validating the driver. All existing hashes and evidence would become stale.
- **Consequences:**
  - You need Vivado 2026.1 installed and the K26 parts available in the free edition **[UNVERIFIED]**.
  - Your `make bit` flow needs a `VIVADO=` path variable.
  - The labs keep 2025.2.
- **Status:** proposed.
- **Confirm/overturn by:** a clean `vivado -mode batch -source scripts/short_wide_*` rebuild on your PC that reproduces the routed timing (WNS ≥ 0), plus the 240-case physical arithmetic check passing on your board. If the course mandates 2025.2 for sign-off, choose (b).

### D-02 Open-vocabulary English, not keyword spotting
- **Decision:** Transcribe open English. Don't switch to a fixed command set.
- **Context:** The brief is "live voice to text", the assessors are industry, and open-vocabulary ASR already runs on this board with PL/CPU parity.
- **Options considered:**
  - (a) Open vocabulary (Citrinet).
  - (b) KWS, DS-CNN-L (95.4 % on 12-class Speech Commands; 497.6 KB fits on chip **[M]** Hello Edge Table 7).
  - (c) Open vocabulary with a lexicon-constrained decoder.
- **Deciding numbers:**
  - KWS fits on chip at 0.16× the budget, but it recognises about 10 words.
  - Citrinet: 3.78/9.60 % LibriSpeech WER **[M]**; 24/269 errors on board diagnostics, identical CPU and FPGA **[M]**.
- **Consequences:** Weights don't fit on chip (9.74 MB = 3.2× **[C]**), so they must stream (D-09). Option (c) stays available as a PS-only fallback (D-21).
- **Status:** proposed.
- **Confirm/overturn by:** if the D-04 sweep shows WER above 25 % on your own recordings at the chosen latency even with the lexicon fallback, reconsider a constrained-vocabulary product.

### D-03 Keep Citrinet-256-LS
- **Decision:** Keep the pinned checkpoint (`a00c8fb7…a21c`) as the model.
- **Context:** The alternatives are compared in review §2.1.
- **Options considered:** QuartzNet 5x5, streaming Zipformer-20M, DS-CNN-L KWS, Citrinet-256.
- **Deciding numbers:**

  | Model | MACs/s **[C]** | Accuracy | Notes |
  |---|---|---|---|
  | Citrinet-256 | 271 M | 3.78/9.60 % test-clean/other **[M]** | 94.1 % pointwise **[C]**; 43.5 % of MACs already on the PL **[C]** |
  | QuartzNet 5x5 | 334 M | 5.39/15.69 % dev-clean/other **[M]** | |
  | Zipformer-20M | — | no WER published **[UNVERIFIED]** | ~21 MB INT8 **[E]**; needs attention, softmax and norms that no RTL exists for |

- **Consequences:** Non-causal, so it needs D-04. A global SE in every block needs D-10.
- **Status:** proposed.
- **Confirm/overturn by:** D-04's WER-vs-right-context curve. If WER loss exceeds 3 pp absolute at R = 0.5 s, re-screen QuartzNet 5x5 (no global SE) with the same sweep.

### D-04 Buffered sliding-window inference
- **Decision:** Use window W = 2.56 s (256 frames, the hardware maximum), hop H = 0.25 s, and emit only tokens at least R before the window end. Start with R = 0.25 s.
- **Context:** The model has global SE (`se_context_size: -1`) and per-feature normalisation (`model_config.yaml:26,33` **[M]**). NeMo's buffered CTC defaults to a 1.6 s chunk in a 4.0 s buffer **[M]** (NeMo script).
- **Options considered:**
  - Whole-utterance (endpointed) decoding: latency is the utterance length.
  - Symmetric-context buffered windows: R = 1.03 s, latency 1.44 s mean **[C]**.
  - Asymmetric buffered windows with small R.
  - Retraining with limited-context SE: infeasible this term.
- **Deciding numbers:** Latency model H/2 + R + C + D: H = 0.25, R = 0.25, C = 40 ms gives **0.43 s mean / 0.56 s worst** **[C]**. R = 0.5 gives 0.68/0.81 s **[C]**.
- **Consequences:**
  - Each second of audio is computed W/H = 10.24 times, i.e. 2.78 GMAC/s **[C]**.
  - PS-only execution would need 68 % of all four cores **[C from M]**, which is why D-06 exists.
  - Also test running normalisation (statistics over the last 5–10 s) against per-window normalisation.
- **Status:** needs-measurement.
- **Confirm/overturn by:** an offline CPU ORT INT8 sweep on the Mac. Use R ∈ {0, 0.25, 0.5, 1.0} s and H ∈ {0.25, 0.5} s, over 200 LibriSpeech dev-clean + dev-other utterances plus the 9 local clips and your own KV260 recordings. Pick the smallest R whose WER is within 1 pp of full-utterance decoding (the snapshot's existing gate).

### D-05 Latency target
- **Decision:**
  - Final text: mean ≤ 0.5 s and p95 ≤ 0.8 s from word end to pixels.
  - Provisional text: ≤ 0.35 s.
  - Zero dropped samples in 30 minutes.
  - At least half of one core idle.
- **Context:** Your starting assumption was 500 ms. Live captions become hard to follow beyond about 1 s **[E]**.
- **Options considered:** 0.5 s (yours), 1.0 s (easy with today's hardware), "as fast as possible" (not testable).
- **Deciding numbers:**
  - Today's shortwide at H = 0.25, R = 0.25: 0.54 s mean, at 59 % duty on four cores **[C]**. That fails the CPU-headroom clause.
  - Whole-encoder PL: 0.43 s mean, about 10 % duty **[C/E]**.
- **Consequences:**
  - The demo needs a word-end → pixel measurement. Use a click or LED marker in the audio plus a photodiode, or timestamped logs against forced-alignment word ends.
  - Add this as a gate next to the existing p50/p95 gates.
- **Status:** needs-measurement (depends on D-04's R).
- **Confirm/overturn by:** a measured latency histogram on the board. If D-04 forces R = 0.5 s, the target becomes 0.7 s mean / 0.9 s p95; document the trade-off.

### D-06 Whole encoder per window on the PL
- **Decision:** The PL executes all 23 blocks plus the 1×1 decoder conv for each window. The PS supplies features and receives INT8 logits.
- **Context:** Today's split is 32 pairs in blocks 1–8, with SE, residual and everything else on the CPU.
- **Options considered:**
  - P1: today's 32 pairs.
  - P2: all 107 pairs, with SE/residual on the CPU.
  - P3: whole encoder.
  - P4: P3 plus the frontend.
- **Deciding numbers:**
  - P1 ceiling **20.5 %** at 1 s even with a zero-time PL; PL busy 6.6 %; MAC share 43.5 % **[C/M]**.
  - P2 keeps ≥ 107 ioctls plus CPU SE/residual. The early per-op design was 2.6× *slower* than CPU **[M]** `RESULTS.md`.
  - P3 at the measured PL efficiency: about 14 ms at 1 s, total ≈ 21 ms, **≈ 80 % lower than CPU** **[C]**; MAC share ≥ 99.9 % **[C]**.
- **Consequences:** The RTL must add:
  - kernels up to 41 (today ≤ 21, `fused_depthwise_channel_wide.sv:5`);
  - stride-2 depthwise and residual convolution (blocks 1/7/14);
  - C_in/C_out up to 640 (block 22 and the decoder);
  - residual add, SE and a layer sequencer.

  ORT is no longer in the inference path for the FPGA mode. The CPU baseline (D-20) still uses ORT.
- **Status:** proposed.
- **Confirm/overturn by:** milestone M3 (one full block from DDR descriptors) must beat that block's optimised CPU subgraph, including all transfers. The snapshot measured block 1 at 51.459 ms on the CPU for the 7.4 s clip **[M]**; re-measure at 2.56 s. Overturn if the block projection can't reach a ≥ 3× per-window speedup.

### D-07 Static descriptor program + one SG-DMA ioctl per window
- **Decision:**
  - **At init:** build a static program in a ~10 MB DMA-coherent buffer. It holds one 64-byte descriptor per layer (op, k, stride, C_in, C_out, T, buffer IDs, flags, requant offset), each followed by that layer's pre-packed weights.
  - **Per window:** copy in 20 KB of features and issue **one ioctl**. The ioctl submits a prepared scatter-gather chain to the existing AXI DMA (MM2S) and waits for 8 KB of logits (S2MM).
  - **Phase 2 option:** a PL AXI master fetches the program itself (doorbell + IRQ).
- **Context:**
  - Today: 32 ioctls per call; `copy_from_user`/`copy_to_user` through bounce buffers (`qn_tile.c:198,327`).
  - 279,552 / 541,696 bytes each way at 0.5 / 1 s **[M]** `shortwide_counter_comparison.json`.
- **Options considered:**
  - per-op ioctl (today);
  - static SG chain over the existing AXI DMA (chosen);
  - PL AXI-master descriptor fetch;
  - UIO + user-space DMA.
- **Deciding numbers:**
  - ioctls per window 32 → 1.
  - Host copies per window ~280–540 KB → ~28 KB **[C]**.
  - Weight stream 9.74 MB per window: 6.1 ms at 1.6 GB/s peak, 12.2 ms at 50 % efficiency **[C]**.
  - Weights arrive in execution order, so they overlap with compute.
- **Consequences:**
  - The driver needs a persistent coherent/CMA buffer and a "run program" ioctl; check the CMA size on the image **[UNVERIFIED]**.
  - The AXI DMA and BD are reused, which keeps Vivado risk low.
- **Status:** proposed.
- **Confirm/overturn by:** driver timers that show submission + completion overhead under 0.5 ms per window. Measure DMA throughput with a weights-only program; if it is under 0.8 GB/s, move to the PL AXI master or to HP1 in parallel.

### D-08 Keep the validated INT8 contract
- **Decision:**
  - UINT8 activations with zero points, INT8 per-channel weights, INT32 bias.
  - Q31 multiplier with nearest-even shift for requantisation, Q16 residual add.
  - INT32 SE sums, Q0.15 gates.
  - INT8 between every layer; INT8 logits out.
  - Channel-major `[C][T]` on chip.
- **Context:** `software/fused/oracle.py` defines this contract and the RTL primitives implement it (`software/fused/README.md` **[M]**).
- **Options considered:** INT32 outputs to the PS (today's style); argmax-only output; this contract.
- **Deciding numbers:**
  - The integer oracle matches FP32 on the diagnostic sets (held-out clean 3/157 vs 3/157; noise 17/84 vs 22/84) **[M]**.
  - INT32 outputs are 4× the bytes **[C]**.
  - Logits are 8.2 KB per window **[C]** and keep lexicon or beam decoding possible.
- **Consequences:** No new quantisation research; the oracle becomes the cocotb golden model (D-18).
- **Status:** proposed.
- **Confirm/overturn by:** representative WER of the integer oracle within 1 pp of FP32 on the D-04 corpus.

### D-09 Activations on chip, weights streamed and double-buffered
- **Decision:**
  - Four 64 KB activation banks (input, output, residual, scratch).
  - A 2 × 461 KB weight double buffer in URAM.
  - SE "replay" is a second pass over the on-chip bank.
- **Context:** Today all 64 URAM hold static weights for 32 pairs (2.23 MB **[C]**).
- **Options considered:**
  - all weights resident (doesn't fit: 9.74 MB vs 3.02 MB);
  - activations in DDR;
  - this split.
- **Deciding numbers:**
  - Largest activation tensor 65,536 B at 256 frames **[C]**.
  - Largest block 461,344 B **[C]**.
  - Total 1.18 MB ≈ 36 URAM **[C]**, which frees ~28 URAM.
- **Consequences:** The window is capped at 256 frames; longer windows need bigger banks, which are affordable from the freed URAM.
- **Status:** proposed.
- **Confirm/overturn by:** zero `weight-starved` cycles on the new counters. If any appear, deepen the buffer or use two HP ports.

### D-10 SE: PL reduction plus PS mailbox (phase 1)
- **Decision:**
  - The PL computes the 256 (or 640) channel sums from the on-chip bank and raises an IRQ.
  - The PS runs the FP32 SE MLP and sigmoid exactly as the oracle does, then writes back 256 Q0.15 gates.
  - The PL applies the gates on the second pass.
  - Phase 2: move the MLP and a sigmoid LUT into the PL.
- **Context:** There are 23 global SE blocks; `fused_se_reduce.v` exists and is simulated.
- **Options considered:** SE fully on the PS (forces activations to DDR); mailbox (chosen); fully in the PL from day one.
- **Deciding numbers:**
  - The SE MLP is 2 × 256 × 32 = 16 K MACs per block **[C]**, 0.07 % of model MACs **[C]**.
  - 23 round trips × 20–60 µs ≈ **0.5–1.4 ms per window** **[E]**.
- **Consequences:** The PS takes one IRQ per block, so it needs tight IRQ affinity; this reuses the snapshot's DMA-IRQ core-pinning work.
- **Status:** proposed.
- **Confirm/overturn by:** measured mailbox round trip; if it is above 100 µs, move to phase 2 early.

### D-11 Keep 512 PW MACs, 64 DW lanes and 100 MHz
- **Decision:** Don't add MACs or raise the clock. Spend the effort on residency and sequencing.
- **Context:** Measured PL efficiency is 196 of 512 MAC/cycle (38 %) **[C]**, and the 1,024-MAC build failed routing with 1,288 node overlaps **[M]**.
- **Options considered:** 1,024 MACs; 150 MHz; INT8 DSP packing (two MACs per DSP48E2); keep as is.
- **Deciding numbers:**
  - Whole-window cycle model: **14.5 ms overlapped vs a 13.6 ms ideal at 512 MACs** **[C]**. Compute is not the bottleneck.
  - Increasing depthwise lanes 64 → 256 changes the estimate by under 1 % **[C]**.
- **Consequences:** DSP use stays around 63–70 % **[E]**, leaving room for the decimator and frontend.
- **Status:** proposed.
- **Confirm/overturn by:** counters showing MAC-issue above 80 % of active cycles together with a per-window latency above target. Only then consider DSP packing.

### D-12 Mic clocking at 48 kHz, decimated in the PL
- **Decision:**
  - Drive BCLK = 3.072 MHz (fs = 48 kHz) from an integer-divided audio clock (24.576 MHz ÷ 8), taken from PS `pl_clk1` or an MMCM.
  - Decimate 3:1 to 16 kHz with a 48-tap polyphase FIR in the PL.
  - Cross into the 100 MHz domain through an XPM async FIFO.
- **Context:** `sph0645_rx.v` produces 1.024 MHz from a 100 MHz NCO (`sph0645_rx.v:2,15` **[M]**).
- **Options considered:**
  - keep 1.024 MHz (out of spec);
  - 2.048 MHz with 2:1 decimation (at the datasheet minimum);
  - integer 100 MHz ÷ 32 = 3.125 MHz (fs 48.83 kHz, which leaves a non-integer 3.05:1 ratio to 16 kHz);
  - 3.072 MHz from an audio clock (chosen).
- **Deciding numbers:**
  - Datasheet f_CLOCK is 2048/3072/4096 kHz (min/typ/max), sleep below 900 kHz; TIE jitter ≤ 2 ns RMS **[M]** (Knowles datasheet).
  - The 100 MHz NCO's edge quantisation gives **2.89 ns RMS** **[C]** (10 ns/√12).
  - The decimator is 0.77 M MAC/s, i.e. one DSP **[C]**.
  - At 48 kHz, TDOA resolution improves 3× (D-13).
- **Consequences:**
  - New clock domain and CDC constraints; update `mic_cdc.xdc`.
  - The decimator also removes the mic's DC offset with a high-pass section. The user recording has a mean of −0.096 FS **[M]** `research/eval/user-stress/PROVENANCE.json`, though its capture source is **[UNVERIFIED]**.
- **Status:** accepted (datasheet constraint).
- **Implementation (2026-10-11):** [`mic-capture-fix/`](../mic-capture-fix/README.md), verified in simulation only. 96-tap Kaiser FIR, measured on the quantised coefficients: passband ±0.004 dB to 6.8 kHz, ≤ −66.5 dB from 9.2 kHz **[C]**. The sampling point is proven in simulation for t_DC 0–150 ns **[M sim]**. MMCM setting: D = 1, M = 10.875, O = 44.25 → 24.576026 MHz **[C]**.
- **Confirm/overturn by:** confirm in the Vivado PS config that `pl_clk1` can reach 24.576 MHz within 0.1 % **[UNVERIFIED]**, otherwise use an MMCM. On the board, a 1 kHz tone recorded at 16 kHz should show the expected frequency and SNR.

### D-13 One mic for ASR; second mic only for DOA
- **Decision:**
  - Capture both I2S slots in RTL.
  - Run ASR on one channel.
  - Fit a second SPH0645 (SELECT = VDD, about 100 mm away) only for an optional GCC-PHAT direction display.
- **Context:** Datasheet: "This allows 2 microphones to operate on a single I2S port" **[M]**. The course XDC also pins a second I2S port **[M]** `hardware/pmod.xdc:13,15,17`.
- **Options considered:**
  - single mic;
  - 2-mic delay-and-sum into ASR;
  - 2-mic DOA demo;
  - 4+ mic array (needs a second bus or TDM, plus more PMOD pins).
- **Deciding numbers:**
  - Diffuse-noise delay-and-sum gain: 0.28 dB at 20 mm, 1.69 dB at 50 mm, 2.77 dB at 100 mm **[C]**.
  - Halving talker distance: +6.0 dB **[C]**.
  - CHiME-4: 6 mics take baseline WER from 23.7 % to 11.5 % **[M]**. No verified 2-mic figure **[UNVERIFIED]**.
  - DOA resolution at 48 kHz and 100 mm: about 4° **[C]**.
- **Consequences:** About 30 LUT/FF for slot two **[E]**; a DOA block of 1–2 DSPs **[E]** if built.
- **Status:** proposed.
- **Confirm/overturn by:** record the demo room with two mics. If delay-and-sum improves WER by ≥ 2 pp on ≥ 50 utterances, promote beamforming to the critical path.

### D-14 Audio ring buffer in the PL
- **Decision:**
  - Replace the 1,024-entry pop-on-read FIFO with a ≥ 1 s, 2-channel, 16-bit ring buffer in 2 URAM.
  - Expose a free-running write pointer and the buffer as a memory window.
  - The PS copies whole blocks with `memcpy`/numpy from an mmap.
- **Context:** The current FIFO is 1,024 × 24 bit, and the IRQ fires at ≥ 160 samples (`voice_axi.v:55,62,63` **[M]**). Python pops one sample per MMIO read.
- **Options considered:** keep the FIFO; deepen the FIFO; ring buffer (chosen); AXI DMA S2MM of audio into DDR.
- **Deciding numbers:**
  - FIFO depth is **64 ms** **[C]**, while inference holds all four cores for 92–170 ms per call **[M]**.
  - A 1 s buffer tolerates 1 s of scheduling stalls; the 2 URAM it needs are freed by D-09.
- **Consequences:** The overflow counter becomes a "samples overwritten before read" counter, and it feeds the zero-drop gate.
- **Status:** accepted (needed to make capture testable).
- **Implementation (2026-10-11):** [`mic-capture-fix/`](../mic-capture-fix/README.md), verified in simulation only. It uses **8,192 frames = 0.512 s in 8 BRAM36**, not URAM: shortwide's URAM is 100 % used **[M]**. That keeps the existing 64 KB window at 0xA000_0000, so the DTS doesn't change. 0.512 s is still 3.0× the longest measured inference (170 ms) **[C]**. A 1 s ring (`RING_AW = 14`) needs a 128 KB window at a new base address.
- **Confirm/overturn by:** 30-minute capture while inference runs at H = 0.25: zero overwritten samples, with the existing `continuous_capture.py` harness adapted.

### D-15 Frontend on the PS for the MVP; PL frontend as stretch
- **Decision:** Compute STFT, mel and log incrementally on the PS (only the new hop's frames), plus normalisation over the window. Move it into the PL after M4.
- **Context:** The brief's step 2 doesn't say where the DSP runs, and Henry's setup notes plan a PL FFT/mel.
- **Options considered:** PS full-window recompute (today); PS incremental; PL streaming FFT-512 → mel-80 → log → normalisation.
- **Deciding numbers:**
  - Measured frontend is 6.09 ms per 1 s full context **[M]**, about 2 ms per hop if incremental **[E]**.
  - FFT + mel is < 3 M MAC/s, under 1 % of encoder MACs **[C]**.
  - Amdahl: at most 6 ms of PS time saved per window.
- **Consequences:**
  - The PL already hosts real DSP through the D-12 decimator.
  - The PL frontend is a showcase and an isolation measure, not a latency need.
  - Fixed-point FFT and log changes the features, so it needs its own WER check.
- **Status:** proposed.
- **Confirm/overturn by:** if PS frontend time per hop exceeds 5 ms, or capture shows contention, promote the PL frontend.

### D-16 Display via DRM/KMS
- **Decision:**
  - Disable GNOME (`multi-user.target`).
  - Render text with a bitmap font into a KMS dumb buffer, using libdrm from C or a thin Python binding.
  - Redraw only the changed rows.
  - Stretch goal: a PL text-mode controller into the DPSUB live-video input.
- **Context:** The overlay's PS has `PSU__DISPLAYPORT__PERIPHERAL__ENABLE = 0` and `PSU__USE__VIDEO = 0` **[M]**. DP on Kria is normally configured by the boot firmware and Linux DT **[UNVERIFIED]**.
- **Options considered:** KMS dumb buffer; fbdev; GTK/Qt under GNOME; PL live video. Connector: DP vs HDMI, which is **not a performance choice**. Both carry the same PS DPSUB output, with HDMI going through the carrier's STDP4320 demux **[M]** ([AMD Smart Camera docs](https://xilinx.github.io/kria-apps-docs/kv260/2022.1/build/html/docs/smartcamera/docs/introduction.html), [AMD forum](https://adaptivesupport.amd.com/s/question/0D54U00006rWnoBSAS/kria-kv260-hdmi?language=en_US)). Use whichever the demo monitor has; prefer native DP (one fewer conversion stage).
- **Deciding numbers:**
  - **Mode: 1920×1080 at 60 Hz, not 4K at 30 Hz** (the KV260 app maximum). The frame period is 16.7 ms vs 33.3 ms, so mean display wait is ≈ 8 ms vs 17 ms and worst ≈ 33 ms vs 67 ms with double buffering **[C]**. The framebuffer is 8.29 MB vs 33.2 MB **[C]**. At 60 Hz the display is ≤ 8 % of the 0.43 s latency budget, worst case.
  - A full 1080p frame is 8.29 MB; a 4-row update is 1.47 MB **[C]**.
  - That is ≤ 1.5 ms per update and **≤ 0.6 % of one core** at 4 updates/s **[E]**.
  - The DPSUB supports a PL live input and alpha blending **[M]** (kernel docs).
- **Consequences:** No desktop on the demo board; SSH remains available.
- **Status:** proposed.
- **Confirm/overturn by:** `modetest -M zynqmp-dpsub` showing a connected DP connector with an overlay loaded, and a measured render time per update.

### D-17 Remove legacy `qn_mac`; pipeline DSPs
- **Decision:** Delete the AXI-Lite `qn_mac` bring-up tile from `voice_axi`. In new RTL, register DSP48E2 A/B, M and P.
- **Context:** The routed critical path is `voice/inst/mac/banks[0].input_mem → accumulator_reg[31]`: 22 logic levels, 9.479 ns, WNS +0.055 ns **[M]** `short_wide_system_timing.rpt`. DRC flags 1,396 DSP input-pipelining, 354 MREG and 194 PREG warnings **[M]** (Vivado DRC).
- **Options considered:** keep it; remove it (chosen); fix only its timing.
- **Deciding numbers:** It is the worst path in the design, and the runtime uses only the AXI DMA path (`qn_tile` driver) **[M]**.
- **Consequences:** `kv260_voice.py`'s MAC bring-up mode stops working; keep it in `archive/`.
- **Status:** proposed.
- **Confirm/overturn by:** routed WNS improving by ≥ 1 ns, and `report_utilization -hierarchical` showing the freed resources.

### D-18 Verilator + cocotb verification
- **Decision:**
  - Wrap XPM memories and DSP48E2 in small modules (`ram_sdp`, `ram_tdp`, `mac_int8`) with `ifdef SYNTHESIS` primitive bodies and behavioural simulation bodies.
  - Write cocotb tests that compare the RTL bit-for-bit with `software/fused/oracle.py` driven by numpy.
  - Keep xsim runs of the real XPM as sign-off.
- **Context:** Verilator 5.048 fails on `xpm_memory_sdpram`, `xpm_memory_tdpram` and `DSP48E2` (MODMISSING) for the shortwide hierarchy **[M]** (run here). Your flow is Verilator + cocotb 2.1.
- **Options considered:** xsim only (today); Verilator with Vivado's unisim sources **[UNVERIFIED]** support; wrappers (chosen).
- **Deciding numbers:** Leaf modules already lint cleanly apart from width warnings **[M]**.
- **Consequences:** The wrapper/primitive equivalence needs one xsim cross-check per wrapper.
- **Status:** proposed.
- **Confirm/overturn by:** the existing 64-case shortwide arithmetic suite re-run under cocotb with identical pass results.

### D-19 Consolidate variants into one tree
- **Decision:**
  - One `rtl/`, one `driver/`, one `runtime/`, one `Makefile`.
  - Move the eight experimental variants and their evidence into `archive/<name>/` unchanged.
  - Initialise git.
- **Context:** 9 runtime variants, 9 driver trees (8 distinct `qn_tile.c`), 8 RTL files all defining `module qn_cached_axis`, 101 duplicate files (4.7 MB) **[M]** (hash scan). The snapshot is not a git repo.
- **Options considered:** keep as is; delete variants; archive them (chosen).
- **Deciding numbers:** The counts above, plus the viva risk of being unable to say which file is in the demo bitstream.
- **Consequences:** Rewrite the Windows-absolute paths in the docs.
- **Status:** proposed.
- **Confirm/overturn by:** `make sim bit deploy` working from the consolidated tree on your Mac → PC → board flow.

### D-20 Honest CPU baseline
- **Decision:**
  - Report three things at the same operating point (W = 2.56 s, H = 0.25 s, same audio, frontend and decoder):
    - (a) best ORT INT8 on the CPU, using the snapshot's screened four-thread policy;
    - (b) a NEON C reference for the per-window encoder, if time allows;
    - (c) PL.
  - Give both per-window latency and live CPU duty.
- **Context:** Henry's setup notes ask for a C/NEON baseline. The snapshot already uses randomised paired runs **[M]**.
- **Options considered:** compare against FP32 (dishonest; INT8 CPU is 27 % faster **[M]**); ORT INT8 only; ORT + NEON.
- **Deciding numbers:** CPU INT8 is 169.5 ms per 2.55 s window **[M]** `RESULTS.md`, i.e. 68 % duty at H = 0.25 **[C]**.
- **Consequences:** Headline claims become "×N per-window latency" and "PS load freed", not percentages on toy inputs.
- **Status:** proposed.
- **Confirm/overturn by:** an independent re-run of the CPU thread/spin screen on the 2.56 s window.

### D-21 Fallbacks
- **Decision:**
  - **Demo fallback:** the current shortwide image with the D-12/D-14 capture fix and the D-16 display, at H = 0.5 s (30 % duty **[C]**; mean latency 0.67 s with R = 0.25 s or 0.92 s with R = 0.5 s **[C]**).
  - **Accuracy fallback:** lexicon-constrained CTC prefix beam search on the PS.
- **Context:** The whole-encoder engine (D-06) is the largest risk on the schedule.
- **Options considered:** no fallback; a CPU-only demo (fails the brief's "use the PL" requirement); shortwide fallback (chosen).
- **Deciding numbers:** Shortwide keeps 43.5 % of MACs on the PL **[C]**, so the fallback still meets "the PL does real inference".
- **Consequences:** M1 delivers a working live demo before any new accelerator RTL exists.
- **Status:** proposed.
- **Confirm/overturn by:** M1 gate: 10 minutes live with zero drops and ≤ 1.2 s p95 latency.
