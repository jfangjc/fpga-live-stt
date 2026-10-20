# KV260 live speech-to-text: review, decisions and mic capture fix

Handoff bundle, 2026-10-11. It reviews the Prototype v2 source snapshot of the same date, which this repository continues.

## Reading order

| # | File | What it is | Time |
|---|---|---|---|
| 1 | [mic-capture-fix/TESTING_AND_NEXT_STEPS.md](mic-capture-fix/TESTING_AND_NEXT_STEPS.md) | **Start here.** What changed, the design decisions, the round 1 test plan with commands and pass criteria, a results sheet to fill in, and what to optimise after round 1 | 30 min |
| 2 | [mic-capture-fix/docs/INTEGRATION.md](mic-capture-fix/docs/INTEGRATION.md) | Step-by-step Vivado / device-tree / software integration checklist, plus the speed impact of the change | 10 min |
| 3 | [docs/ARCHITECTURE_REVIEW.md](docs/ARCHITECTURE_REVIEW.md) | Review of the whole design: model choice, PS/PL partition (Amdahl bounds from the shortwide counters), mic array, display, ranked weaknesses, target architecture and PL budget | 30 min |
| 4 | [docs/DECISIONS.md](docs/DECISIONS.md) | 21 decision records (D-01 … D-21): options considered, the numbers that decided each, and how to confirm or overturn it | reference |
| 5 | [docs/ROADMAP.md](docs/ROADMAP.md) | Milestones M0–M5 to demo day with verification gates, and risks | 10 min |
| — | [docs/analysis/](docs/analysis/README.md) | Standard-library Python that reproduces every computed **[C]** number (MAC counts, cycle model, memory budget, latency, array gain) | — |
| — | [mic-capture-fix/](mic-capture-fix/README.md) | RTL, cocotb tests, constraints, block-design patch, PS reader, board benchmark | — |

## Quick start

On macOS, Linux or WSL, with Verilator ≥ 5.036, cocotb 2.1 and pytest installed:

```bash
cd mic-capture-fix
```

```bash
make
```

```bash
make bench-dry
```

Expected: `lint: clean`, `6 passed`, `5 passed`, `dc_gain 6/6`, `decim3 4/4`, `i2s_rx 8/8`, `top 4/4`. `bench-dry` reports zero losses.

To re-run the analysis scripts, run the commands in [docs/analysis/README.md](docs/analysis/README.md).

## Notes on the review documents

- **"You/your" in `docs/` means Henry's setup.** The review was written for Henry:
  - a Mac for simulation;
  - a Windows PC with Vivado **2025.2** (board files 1.2–1.4);
  - a KV260 on **Ubuntu 22.04, kernel 5.15**.

  D-01 recommends standardising on *your* snapshot platform instead: Vivado 2026.1, Ubuntu 24.04, kernel 6.8.0-1015-xilinx. The mic-capture-fix documents are written for you.
- **Henry's setup notes** are private and not included. The three facts they contribute:
  1. Henry's toolchain, as above.
  2. The preferred verification flow is Verilog plus Verilator and cocotb 2.1, bit-accurate against golden models, with waveforms in Surfer.
  3. **Board safety:** never access 0xA00x_xxxx unless an AXI overlay is loaded *with clocks on*. An unanswered AXI access freezes the board until power-cycled.
- **Evidence tags:**
  - **[M]** measured, with a file or source;
  - **[C]** computed, reproducible with `docs/analysis/` or the RTL tests;
  - **[E]** estimated, with assumptions stated;
  - **[UNVERIFIED]** not checked.

  Paths in the docs without a folder prefix (e.g. `reports/fused/...`, `rtl/...`) are relative to the repository root.
- **Status:**
  - The mic capture fix is verified in simulation only: lint clean, 22/22 cocotb tests, 11/11 pytest checks.
  - Nothing has been synthesised or run on the board. Round 1 (your testing) is the first hardware contact.
  - Several steps that depend on your Windows build flow are marked **[UNVERIFIED]** because you know that flow best: synth/implement script interplay, evidence binding, and the clock node name.

## What to send back

Everything listed in §6 of the testing guide:
- the filled-in results table;
- the `t*.json` files from `bench_capture.py`;
- `reports/audio_*.rpt`;
- scope screenshots;
- `t3_speech.wav`.
