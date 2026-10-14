# Mic capture fix (D-12, D-13, D-14)

`audio_capture_axi` is a drop-in replacement for the snapshot's `voice_axi` microphone block. It is verified in simulation only; it has not been synthesised or run on the board yet. **Start with [TESTING_AND_NEXT_STEPS.md](TESTING_AND_NEXT_STEPS.md)**, which covers what changed, the design decisions, the round 1 test plan, a results sheet, and what to optimise after round 1. [docs/INTEGRATION.md](docs/INTEGRATION.md) is the step-by-step integration checklist.

## What it fixes

| Problem in the current design | Evidence | Fix |
|---|---|---|
| The mic is clocked below its datasheet minimum | BCLK 1.024 MHz (`rtl/sph0645_rx.v:2`). SPH0645 needs 2.048–4.096 MHz and sleeps below 0.9 MHz | BCLK = 3.072 MHz (fs = 48 kHz) from a 24.576 MHz MMCM clock |
| BCLK edge jitter exceeds spec | The 100 MHz NCO quantises edges to 10 ns, giving 2.89 ns RMS against a 2 ns limit | Integer ÷8 of a clean MMCM clock |
| The FIFO holds only 64 ms | 1,024 × 24-bit pop-on-read FIFO (`voice_axi.v:55`), while one inference keeps the PS busy for 92–170 ms | 8,192-frame ring buffer (0.512 s), read in bulk, with write/read counters and overrun accounting |
| Only the left slot is captured | `sph0645_rx.v:4` | Both I2S slots captured, so a second mic (SELECT = VDD) needs no new pins |
| Large DC offset | The recording's mean is −0.096 FS | DC blocker (≈ 5 Hz corner) before the gain stage |
| The routed critical path is in the legacy `qn_mac` | WNS +0.055 ns, 22 logic levels (`reports/fused/short_wide_system_timing.rpt`) | The new block doesn't contain `qn_mac` |

## Pipeline

```
aud_clk 24.576 MHz                                              | s_axi_aclk 100 MHz
i2s_rx_stereo  ->  decim3_fir (96-tap, 3:1)  ->  dc_gain x2  ---+-> toggle CDC -> ring (8 BRAM36) -> AXI-Lite
48 kHz, 18-bit     16 kHz, 20-bit                16-bit, +24 dB |    seq-checked   {R16,L16} words    same 64 KB window
```

## Layout

| Path | Contents |
|---|---|
| `rtl/` | `audio_capture_axi.v` (top level, AXI-Lite, ring, CDC), `i2s_rx_stereo.v`, `decim3_fir.v`, `dc_gain.v`, generated `decim3_coeffs.vh` |
| `sim/` | cocotb 2.1 tests, a bus model of two SPH0645s (`sph0645_bfm.py`), an AXI-Lite master (`axil.py`), bit-exact golden models in pure Python integers (`golden.py`) |
| `sw/` | `audio_ring.py`: PS-side ring reader and WAV-capture CLI, with a pytest against a fake device. `bench_capture.py`: round 1 board benchmark (losses, reader CPU, read gaps, frame rate, tone and DC under load) |
| `constraints/audio_cdc.xdc` | Replaces `hardware/mic_cdc.xdc` |
| `scripts/` | `gen_coeffs.py` (filter design), `bd_patch_audio.tcl` (block-design swap), `summarise_results.py` |
| `docs/INTEGRATION.md` | Required changes, speed impact, review checklist |

## Run

You need Verilator ≥ 5.036, cocotb 2.1 and pytest; numpy is not required. Then:

```bash
source ~/.venvs/hdl/bin/activate
```

```bash
make
```

```bash
make sim DUT=top WAVES=1
```

```bash
make waves DUT=top
```

Results on 2026-10-11 (Verilator 5.048, cocotb 2.1.0, Python 3.14, macOS):

| Suite | Result | What it shows |
|---|---|---|
| `make lint` | clean | `verilator -Wall`, whole hierarchy |
| `test_coeffs.py` | 6/6 | DC gain exactly 1; linear phase; passband ±0.004 dB to 6.8 kHz; stopband ≤ −66.5 dB from 9.2 kHz; RTL include matches the golden coefficients |
| `test_audio_ring.py` | 5/5 | In-order reads, ring wrap, falling behind, writer lapping during a read, 32-bit counter wrap |
| `i2s_rx` | 8/8 | BCLK 3.072 MHz with 50 % duty and WS = BCLK/64; two mics share one line with no contention; exact capture for t_DC 0–150 ns; capture fails at 200 ns (proves the sampling point); single mic leaves right = 0 |
| `decim3` | 4/4 | Bit-exact for random, tone and full-scale input; 1 kHz −0.03 dB; 12 kHz (aliases to 4 kHz) −91 dB; overlap flag works |
| `dc_gain` | 6/6 | Bit-exact at gain 0/4/8/12 (12 clamps to 8); −0.1 FS DC removed to 0.375 LSB residual; saturation |
| `top` | 4/4 | 50 stereo frames bit-exact end to end through both clock domains; registers and SLVERR cases; IRQ, fill, overrun and soft clear; disable/restart with no CDC drops |
