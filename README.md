# KV260 speech-to-text accelerator, prototype v1

English QuartzNet15x5 speech recognition on the Kria KV260, with the pointwise
convolutions offloaded to custom INT8 RTL in the PL. An SPH0645 I2S microphone
is captured in the PL. The CPU runs the audio frontend, the depthwise
convolutions, the rest of the graph and the CTC decoder.

This repository holds the whole v1 iteration (8–9 October 2026): the
microphone and AXI-Lite dot-product prototype, a DMA tile accelerator, six
software and driver updates, and a cached-layer engine that keeps each layer's
weights in UltraRAM.

## Result

All times are for the same 10 s recording on the KV260, DC removed, model
already loaded. Every hybrid run produced the same transcript as the CPU.

| Configuration | Total time | RTF |
|---|---:|---:|
| CPU only, ONNX Runtime, 4 threads | 1.965 s | 0.197 |
| First DMA hybrid, one tile per ioctl | 27.71 s | 2.771 |
| Best tile hybrid (batched, native CPU depthwise) | 6.303 s | 0.630 |
| Cached-layer hybrid (final design) | 3.499 s | 0.350 |

The FPGA hybrid never beat the CPU. The final cached design is 1.78x slower
than CPU-only inference. Even with zero time inside DMA ioctls it would take
about 2.41 s, because quantization, packing and result handling on the host
cost more than the CPU convolutions they replace.

Not measured: accuracy on a speech corpus (WER) and live capture-to-text
latency.

[RESULTS.md](RESULTS.md) has the full history.

## Model

NVIDIA `stt_en_quartznet15x5`, as the OpenVoiceOS FP32 ONNX export
(`OpenVoiceOS/stt_en_quartznet15x5_onnx`, revision `7a98393`).

- **Frontend:** 64 Slaney mel bins, FFT 512, 320-sample Hann window,
  160-sample hop, pre-emphasis 0.97, per-feature normalization.
  Implemented in NumPy in `software/asr-baseline/quartznet_cpu.py`.
- **Graph:** 171 convolutions: 94 pointwise (run on the FPGA in INT8) and
  77 depthwise (run on the CPU in FP32).
- **Quantization:** dynamic, with no calibration corpus. Per-layer activation
  scale and per-channel weight scale (absolute maximum / 127), INT32 sums.

The runner matches the original NeMo checkpoint: identical frame decisions on
the 10 s clip and at 16000, 16001 and 32000 samples, with a maximum
log-probability error of 0.0013.

## Hardware

Three Vivado designs, all for `xck26-sfvc784-2LV-c` at 100 MHz:

| Design | Project | Contents | Routed setup / hold |
|---|---|---|---|
| V1 | `Prototype.xpr` | SPH0645 capture FIFO and 32-lane INT8 dot product on AXI-Lite (`rtl/voice_axi.v`, `rtl/qn_mac.v`) | +0.353 / +0.028 ns |
| V2 DMA | `voice_dma/voice_dma.xpr` | AXI DMA and the QNT1 16x16 tile engine (`rtl/qn_tile_axis.v`) | +0.198 / +0.010 ns |
| V3 cached | `voice_cached_dma/voice_cached_dma.xpr` | AXI DMA and the QNC2 cached-layer engine (`rtl/qn_cached_axis.v`) | +0.192 / +0.010 ns |

The board runs Ubuntu 24.04.2 with kernel `6.8.0-1015-xilinx`. Designs are
loaded with `xmutil` as `PL_FLAT` applications. XRT and the DPU are not used.

## Layout

| Path | Contents |
|---|---|
| `Prototype.xpr`, `Prototype.srcs/` | V1 Vivado project: PS, microphone and dot-product block design, constraints |
| `voice_dma/`, `voice_cached_dma/` | V2 and V3 Vivado projects, created by `scripts/create_*_prototype.tcl` |
| `tile_check/` | Standalone tile synthesis project (`scripts/tile_ooc.tcl`) |
| `build/` | Generated cached-engine simulation project and V3 top-level wrapper |
| `rtl/` | Verilog: microphone receiver, AXI-Lite peripheral, dot product, tile and cached engines, DMA top level |
| `tb/`, `sim/` | XSIM testbenches, tile vectors and host validation scripts |
| `scripts/` | Vivado build Tcl, bootgen `.bif` files and package builders (`build_dma_*.py`) |
| `reports/` | Timing, utilization and DRC reports, simulation logs and board measurement JSON |
| `software/` | Board software, ASR runners and the `qn_tile` driver; see [software/README.md](software/README.md) |
| `deployment/` | V1 board package; see [deployment/README.md](deployment/README.md) |
| `dma-deployment/` | Base DMA board package; see [dma-deployment/README.md](dma-deployment/README.md) |
| `dma-status-fix/`, `dma-batch-update/`, `dma-packing-update/`, `dma-cpu-conv-update/`, `dma-reuse-update/`, `dma-native-conv-update/` | Incremental update packages applied on top of `dma-deployment/` |
| `dma-cached-update/` | V3 cached-layer package; see [dma-cached-update/README.md](dma-cached-update/README.md) |

Each package folder holds the files that were copied to the board and a
`validation/` folder with the host and board results for that stage.
Bitstreams, compiled overlays, kernel modules, the ONNX model and recordings
are not committed.

## Build

Tools: Vivado 2026.1 with the KV260 SOM board preset installed.

V1, from the Vivado Tcl Console with `Prototype.xpr` open:

```tcl
source scripts/build.tcl      ;# starts synthesis
source scripts/implement.tcl  ;# after synthesis completes
source scripts/export.tcl     ;# after the bitstream; writes reports and voice_prototype.xsa
```

`rebuild32.tcl` (called by `build.tcl`), `implement.tcl` and `export.tcl` set
`root` to `C:/Users/jfang/Documents/Vivado/Prototype`; edit it for another
checkout.

V2 DMA design:

```tcl
source scripts/create_dma_prototype.tcl
source scripts/dma_synth.tcl
source scripts/finish_dma_rebuild.tcl   ;# waits, implements and exports reports
```

V3 cached design. Simulate the engine first; the build refuses to export an
XSA if routed timing fails:

```tcl
source scripts/cached_sim.tcl
source scripts/create_cached_dma_prototype.tcl
source scripts/cached_dma_build.tcl
```

Convert a bitstream for `xmutil` and compile its overlay, for example:

```sh
bootgen -arch zynqmp -image scripts/voice_dma_bitstream.bif -process_bitstream bin -w on
dtc -@ -I dts -O dtb -o voice-dma.dtbo dma-deployment/voice-dma/voice-dma.dts
```

Board installation is in [deployment/README.md](deployment/README.md) (V1),
[dma-deployment/README.md](dma-deployment/README.md) (DMA tile) and
[dma-cached-update/README.md](dma-cached-update/README.md) (cached).
