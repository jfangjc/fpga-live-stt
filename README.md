# KV260 speech-to-text accelerator, prototype v3

Speech recognition on the Kria KV260 with custom INT8 RTL in the PL. Prototype
v3 continues Prototype v2 and covers:

- **Citrinet-256:** the retained-block accelerator that runs about 2x faster
  than the best CPU baseline on short inputs (9–14 October 2026).
- **MVP:** that design packaged as `kv260-asr-mvp` 1.0.1, a one-command WAV
  transcriber, and tested on a clean install (15 October).
- **Whisper:** base, small and large-v3-turbo on the bulk matrix engine through
  whisper.cpp (17–20 October).

## Results

| Workload | Input | Best CPU p50 | FPGA hybrid p50 | Speedup |
|---|---|---:|---:|---:|
| Citrinet-256, final audit | 0.5 s | 52.6 ms | 26.1 ms | 2.01x |
| | 1 s | 93.8 ms | 35.8 ms | 2.62x |
| | 2.5 s | 145.4 ms | 59.0 ms | 2.47x |
| Citrinet-256, MVP clean-install retest | 0.5 s | 52.1 ms | 26.1 ms | 1.996x |
| | 1 s | 93.8 ms | 35.8 ms | 2.62x |
| | 2.5 s | 145.4 ms | 59.4 ms | 2.45x |
| Whisper base | 3.5–23.3 s | 16.9–19.1 s | 6.8–9.1 s | 2.10–2.49x |
| Whisper small | 3.5–23.3 s | 58.4–63.8 s | 19.5–24.9 s | 2.57–2.99x |
| Whisper large-v3-turbo | 3.5–23.3 s | 335–338 s | 96–116 s | 2.91–3.50x |

- **Citrinet:** 300 randomized, paired warm runs per input. Timing covers the
  frontend, model, decoder, every weight upload, DMA transfer and
  synchronization. FPGA logits match the CPU bit for bit.
- **Whisper:** three complete CLI runs per clip, including model loading. FPGA
  word errors on a 244-word sample equal or beat FP16 CPU.

Outcome:
- Citrinet meets 2x on the tested inputs. It accepts at most 256 feature
  frames (about 2.55 s) and is not causal.
- Every Whisper model passes 2x but is far too slow for live captions, because
  whisper.cpp always encodes a full 30 s window.
- Not qualified: live microphone capture and accuracy on a representative
  corpus.

[RESULTS.md](RESULTS.md) has the full history and the reasons.

## Models and hardware

| Item | Value |
|---|---|
| Citrinet model | `nvidia/stt_en_citrinet_256_ls`, about 9.8M parameters, WordPiece CTC, 80-mel frontend |
| Citrinet image | `asr-v3-branch512-ab166`: 512 pointwise MACs, 64 depthwise lanes, 166.667 MHz, routed setup +0.043 ns |
| Citrinet resources | 68,136 LUTs, 83.5 BRAM tiles, 16 URAM, 577 DSPs |
| Whisper models | `openai/whisper-base`, `whisper-small`, `whisper-large-v3-turbo`, multilingual, Q8_0 weights |
| Whisper runtime | whisper.cpp v1.8.3 with a matrix hook to `asr-v3-bulk` (512 MACs, 100 MHz) |
| Board | KV260, Ubuntu 24.04, kernel 6.8.0-1036-xilinx, Python 3.12, four Cortex-A53 cores at 1.33 GHz |

The FPGA is driven through the Linux AXI DMAengine and a small `qn_tile`
character driver. XRT and the DPU are not used.

## Layout

| Path | Contents |
|---|---|
| `Prototype_v2.xpr`, `Prototype_v2.srcs/` | Base Vivado project: PS, microphone, AXI DMA and the QNC2 cached engine |
| `rtl/` | Accelerator and microphone RTL; `rtl/experimental/` holds the pair, chain, stream and branch512 engines |
| `sim/` | Testbenches and fixtures |
| `scripts/` | Vivado build scripts, firmware gating (`prepare_*_firmware.py`), board runners (`run_*_board.sh`) and MVP packaging |
| `hardware/` | Microphone CDC and PMOD constraints |
| `software/` | Runtimes, ORT custom operators, benchmarks, the MVP CLI and the Whisper bridge; see [software/README.md](software/README.md) |
| `deployment/` | Device-tree overlays, drivers and app firmware per design; see [deployment/README.md](deployment/README.md) |
| `verification/` | Independent audits, acceptance gates and test vectors; see [verification/README.md](verification/README.md) |
| `research/` | Model export metadata and evaluation manifests; see [research/README.md](research/README.md) |
| `reports/` | Timing, utilization and DRC reports and board measurements (`fused/` Citrinet, `mvp/`, `whisper*/`) |
| `kv260-asr-handoff-2026-10-11/` | External review bundle, including a reworked microphone capture path |
| `SOURCE_MANIFEST.json` | File inventory of the 15 October snapshot |

Bitstreams, XSAs, compiled drivers, model files, release archives and
recordings are build outputs and are not committed. Design-variant Vivado
projects are generated into `build/`.

## Build

Tools: Vivado/Vitis 2026.1, part `xck26-sfvc784-2LV-c`, board
`xilinx.com:kv260_som:part0:2.0`.

The final Citrinet image:

```powershell
$vivado = 'C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat'
& $vivado -mode batch -source scripts/mvp_project.tcl -tclargs check
& $vivado -mode batch -source scripts/mvp_project.tcl -tclargs build
```

- `check` recreates the project from the saved block design and checks it.
- `build` synthesizes, routes and exports an XSA under `deployment/mvp-rebuild`.
  It refuses to export unless setup ≥ 0.001 ns, hold ≥ 0 and DRC is clean.
- The original flow is `scripts/branch512_ab166_synth.tcl`, then
  `scripts/branch512_ab166_implement.tcl`, then
  `scripts/prepare_branch512_ab166_firmware.py`.

Every other design has its own `scripts/<variant>_*.tcl` build scripts and a
`scripts/prepare_<variant>_firmware.py` gate. The base image uses
`scripts/build_v2.tcl` (run `scripts/new_project.tcl` first in a fresh
checkout).

The Whisper path needs no new FPGA image: it reuses `asr-v3-bulk`
(`scripts/bulk_system_build.tcl`).

## Run

- Citrinet MVP: [software/mvp/README.md](software/mvp/README.md).
- Whisper: [software/whisper/README.md](software/whisper/README.md).
- Installing firmware and rolling back: [deployment/README.md](deployment/README.md).
