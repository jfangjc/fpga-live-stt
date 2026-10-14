# KV260 speech-to-text accelerator, prototype v2

Citrinet-256 speech recognition on the Kria KV260, with the convolution layers
offloaded to custom INT8 RTL in the PL. The CPU runs the audio frontend, the
remaining graph operators and the CTC decoder. Everything runs through one
ONNX Runtime session, with the FPGA blocks registered as native custom operators.

This repository holds the whole v2 iteration (9–15 October 2026): the first
pointwise-offload build, which was slower than CPU, through to the retained
block design that is about 2x faster than the best CPU baseline on short inputs.

## Result

Final design: `asr-v3-branch512-ab166`, 512 pointwise MACs and 64 depthwise
lanes at 166.667 MHz (routed setup +0.043 ns, hold +0.010 ns).

| Input | Best CPU p50 | FPGA hybrid p50 | Speedup | CPU p95 | Hybrid p95 |
|---|---:|---:|---:|---:|---:|
| 0.5 s | 52.6 ms | 26.1 ms | 2.01x | 60.1 ms | 27.0 ms |
| 1 s | 93.8 ms | 35.8 ms | 2.62x | 96.8 ms | 49.2 ms |
| 2.5 s | 145.4 ms | 59.0 ms | 2.47x | 148.4 ms | 65.1 ms |

- Each row is 300 randomized, paired warm runs.
- Timing covers the frontend, model, decoder, every weight upload, DMA
  transfers and synchronization.
- The CPU baseline is the fastest of 64 screened thread and graph policies.
- FPGA logits are bit-exact with the integer oracle and the CPU graph.

The audit is in `reports/fused/FPGA_ASR_2X_COMPLETION_AUDIT.json`.

Limits:

- **Input length:** at most 256 feature frames (about 2.55 s).
- **Not causal:** the model has global squeeze-and-excitation (SE) blocks, so
  each input window is processed as a whole.
- **Not qualified:** live microphone capture and accuracy on a representative
  corpus.

[RESULTS.md](RESULTS.md) has the full history of how the design got here.

## Model

`nvidia/stt_en_citrinet_256_ls` at revision `c7cdacff`, about 9.8M parameters.

- **Tokenizer:** WordPiece with 256 tokens plus a CTC blank. The model card says
  SentencePiece, but the archive is WordPiece.
- **Frontend:** 80 mel bins, FFT 512, 400-sample window, 160-sample hop.
- **Encoder:** 23 blocks of depthwise and pointwise convolutions with masks,
  residuals and global SE.

The exported ONNX graph matches the original NeMo 1.23 model on real audio:
same lengths, same frame predictions, same text. Larger Citrinet-512 and
Citrinet-1024 models were screened as well; see [research/](research/README.md).

## Layout

| Path | Contents |
|---|---|
| `Prototype_v2.xpr`, `Prototype_v2.srcs/` | Base Vivado project: PS, microphone, AXI DMA and the QNC2 cached accelerator |
| `rtl/` | Base accelerator and microphone RTL; `rtl/experimental/` holds the retained-pair, chain, stream and branch512 engines |
| `sim/` | Testbenches and fixtures |
| `scripts/` | Vivado build scripts (`*_system_build.tcl`, `*_synth.tcl`, `*_implement.tcl`), firmware gating (`prepare_*_firmware.py`) and board runners (`run_*_board.sh`) |
| `hardware/` | Microphone CDC and PMOD constraints |
| `software/` | Native runtimes, ORT custom operators and benchmarks; see [software/README.md](software/README.md) |
| `deployment/` | Device-tree overlays, drivers and app firmware per design; see [deployment/README.md](deployment/README.md) |
| `verification/` | Independent audits and acceptance-gate tools; see [verification/README.md](verification/README.md) |
| `research/` | Model acquisition, export and model notes |
| `reports/` | Timing, utilization and DRC reports, plus board measurement summaries |
| `kv260-asr-handoff-2026-10-11/` | External review bundle, including a reworked microphone capture path |

Vivado projects for each design variant are generated into `build/` by the
scripts. That folder, the bitstreams, model files and recordings are not
committed.

## Build

Tools: Vivado/Vitis 2026.1, part `xck26-sfvc784-2LV-c`, board
`xilinx.com:kv260_som:part0:2.0`. The board runs Ubuntu 24.04 with
kernel 6.8.0-xilinx.

Base image:

```powershell
& 'C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat' -mode batch -source scripts/cached_sim.tcl
& 'C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat' -mode batch -source scripts/build_v2.tcl
```

In a fresh checkout without `Prototype_v2.xpr`, run `scripts/new_project.tcl`
first. `build_v2.tcl` refuses to export an XSA unless routed timing and DRC pass.

Every later design variant has its own script pair:
- `scripts/<variant>_system_build.tcl` builds it.
- `scripts/prepare_<variant>_firmware.py` gates and packages its firmware.

The final design uses `scripts/branch512_ab166_synth.tcl` and
`scripts/branch512_ab166_implement.tcl`, then
`scripts/prepare_branch512_ab166_firmware.py`.

Board installation and rollback are in [deployment/README.md](deployment/README.md).
