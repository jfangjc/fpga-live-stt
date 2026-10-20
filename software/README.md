# Software

Board software runs on the KV260 under Ubuntu 24.04 with Python 3.12, using the
pinned packages in `requirements-runtime.txt`. Native libraries are built on the
board with `build.sh` in each directory, or `make` for `native/`.

## Shared tools

| Directory | Purpose |
|---|---|
| `model-tools/` | Downloads the Citrinet checkpoint, exports it to ONNX and validates it against the original NeMo model |
| `fused/` | Integer arithmetic oracle, calibration, ORT INT8 CPU graph builder and block profiling |
| `latency/` | Resident transcription API, latency benchmarks, CPU policy screens, graph simplification and the final confirmation scripts |
| `evaluation/` | Paired CPU/FPGA benchmark and WER harness |
| `mvp/` | `kv260-asr-mvp` WAV transcriber for the final design; see [mvp/README.md](mvp/README.md) |
| `whisper/` | whisper.cpp patch, FPGA matrix bridge, board runner and benchmarks; see [whisper/README.md](whisper/README.md) |
| `capture/` | Continuous microphone capture from the PL FIFO |
| `native/` | `libqnc`, the native QNC2 host used by the first runtime |
| `runtime/` | First runtime: 126 offloaded pointwise layers with the rest in CPU regions |

`CACHED_LAYER_PROTOCOL.md` specifies the QNC2 packet format and ioctl ABI
behind the base engine.

## FPGA custom operators

Each `ort_fpga_*` directory is one design iteration. It holds an ONNX Runtime
custom-operator library (`pointwise.cc`, `qnc_transport.c`) and the graph
rewriter that inserts its operators. Each library needs its matching firmware
and driver from `deployment/`.

| Directory | Design | What it offloads |
|---|---|---|
| `ort_fpga` | `asr-v3-quant` | Pointwise layers, with bias and requantization done on the FPGA |
| `ort_fpga_bulk` | `asr-v3-bulk` | 512-MAC pointwise engine that keeps the input on chip; `transcribe.py` runs it |
| `ort_fpga_prepacked`, `ort_fpga_screen` | `asr-v3-bulk` | Control experiments: prepacked weights, and screening that includes weight reloads |
| `ort_fpga_quad` | `asr-v3-quad` | 1,024-MAC version; failed routing |
| `ort_fpga_pair` | `asr-v3-pair` | One depthwise/mask/pointwise pair |
| `ort_fpga_cache` | `asr-v3-cache` | Four pairs with resident weights |
| `ort_fpga_shortcache` | `asr-v3-shortcache` | 32 resident pairs, depthwise kernels 11 to 21, up to 256 frames |
| `ort_fpga_shortwide` | `asr-v3-shortwide` | The same with 64 depthwise lanes |
| `ort_fpga_chain` | `asr-v3-chain`, `asr-v3-chain-prefetch` | 32 pairs fused into 10 chains |
| `ort_fpga_overlap`, `ort_fpga_overlap_session`, `ort_fpga_pipeline`, `ort_fpga_pipeline_pinned` | `asr-v3-chain` | CPU residual overlap experiments; not adopted |
| `ort_fpga_stream`, `ort_fpga_stream_exact` | `asr-v3-stream` | 100 pairs with streamed weights; `_exact` matches ARM ORT rounding |
| `ort_fpga_stream_registered` | `asr-v3-stream`, `asr-v3-adaptive` | Fixed program parts kept in registered kernel DMA buffers |
| `ort_fpga_stream_branch`, `ort_fpga_stream_branch_transport` | 1,024-MAC residual design | Adds the residual projections; never routed |
| `ort_fpga_stream_branch512` | `asr-v3-branch512-ab166` | 512-MAC residual design at 166.7 MHz |
| `ort_fpga_stream_branch512_neon` | `asr-v3-branch512-ab166` | The same with NEON output unpacking; used for the final result and the MVP |

Rules shared by every operator library:
- Physical errors propagate to the caller. There is no silent CPU fallback.
- Every weight upload is counted inside the timed call.
- Constant weights and quantization parameters must be graph initializers.
- `build.sh` needs the ONNX Runtime 1.30.0 C API headers in an `include/`
  folder next to it. Copy them from the
  [ORT v1.30.0 release](https://github.com/microsoft/onnxruntime/tree/v1.30.0/include/onnxruntime/core/session).
