# Latency benchmarks and resident API

This directory holds the scripts that produced every result in
[RESULTS.md](../../RESULTS.md) from section 2 onwards. Most are named after the
design they measure:

| Prefix | Purpose |
|---|---|
| `tune_*`, `*_screen.py` | Short randomized screens that pick the CPU thread, spin and graph policy |
| `validate_*_physical.py` | Physical FPGA runs compared with the integer oracle and the CPU output |
| `confirm_*.py` | 300-pair paired confirmation runs; these give the reported numbers |
| `*_benchmark.py` | Shared benchmark harnesses, each building on the previous design's harness |

Other tools:

| File | Purpose |
|---|---|
| `resident.py` | `ResidentTranscriber`: one session kept loaded, taking 16 kHz mono float32 audio and returning text, timings and FPGA counters |
| `eliminate_duplicates.py`, `validate_cse.py` | Graph simplification (5,109 to 1,411 nodes) and its exactness check |
| `frontend_valid_frames.py` | Exact frontend that drops padding beyond the valid length; used for the final result |
| `dma_irq.py` | Moves the PL DMA interrupts to a chosen CPU core |

Reproducing the final result on the board takes three steps, run as root from
the deployed project directory:

```sh
sh scripts/run_branch512_ab166_board.sh software/latency/validate_branch512_ab166_vf_physical.py --out reports/fused/vf_physical.json
sh scripts/run_branch512_ab166_board.sh software/latency/tune_branch512_ab166_vf_policy.py --out reports/fused/vf_policy.json
sh scripts/run_branch512_ab166_board.sh software/latency/confirm_branch512_ab166_vf_latency.py --policy reports/fused/vf_policy.json --runs 300 --out reports/fused/vf_confirmation.json
```

- **Firmware:** the runner loads the `asr-v3-branch512-ab166` firmware and
  driver, and switches the board back to the 100 MHz bulk image afterwards.
- **Board idle:** run one board job at a time, with nothing else running.
