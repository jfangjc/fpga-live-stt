# KV260 speech-to-text accelerator, prototype v4: Moonshine Small optimization

Moonshine streaming speech recognition on the Kria KV260, with the encoder
feed-forward projections offloaded to the existing INT8 bulk matrix engine in
the PL. The CPU runs the frontend, attention, the decoder and control.

This is a snapshot of Prototype v4 from 21 October 2026. It focuses on one
task: making the Moonshine Small FPGA hybrid path faster. The Prototype v4
Citrinet-256 runtime is still included and unchanged.

## Result

Final Small profile: native ARM encoder kernels, cached FPGA weight packets,
a native INT8 decoder with run-spin scheduling, 2500 ms updates, four threads.

| Audio | Previous FPGA p50 | New FPGA p50 | New FPGA worst | CPU INT8 p50 | CPU ÷ FPGA |
|---|---:|---:|---:|---:|---:|
| 2.5 s | 2.420 s | 1.977 s | 1.984 s | 2.270 s | 1.15x |
| 5 s (repeated clip) | 4.893 s | 4.066 s | 4.074 s | 3.976 s | 0.98x |

- The FPGA path is about 18% faster than the previous FPGA version.
- **The 2x FPGA-versus-CPU target is not met.** The fastest CPU pass on the
  2.5 s clip was 1.943 s.
- Times are cumulative processing over all partial updates and finalization.
  They exclude initialization and audio capture.
- One warmup and three measured passes per case.
- Every FPGA pass matched the integer oracle at every update and reached EOS.

Limits:

- **Accuracy:** checked on one clip only. No held-out WER.
- **Update interval:** with 1 s updates, Small takes about 2.65 s for 2.5 s of
  audio, so it is not real time.
- **Not qualified:** live microphone capture, long utterances, sustained
  thermal behavior.

[evidence/RESULTS.md](evidence/RESULTS.md) has all numbers and what was tried.

## Hardware and software

| Item | Value |
|---|---|
| Board | AMD Kria KV260 (K26), Ubuntu ARM64, kernel `6.8.0-1036-xilinx` |
| Python | 3.12 |
| Moonshine FPGA image | `asr-v3-bulk`: 100 MHz bulk INT8 matrix engine. No new bitstream. |
| Citrinet FPGA image | `asr-v3-branch512-ab166`: 512 pointwise MACs, 64 depthwise lanes, 166.667 MHz |
| Models | `moonshine-ai/moonshine-streaming-small` (default) and `moonshine-ai/moonshine-streaming-tiny`, revisions pinned in `software/moonshine/model.py` |
| Runtimes | PyTorch 2.8.0 (CPU), ONNX Runtime 1.24.1 for the native encoder and decoder |
| FPGA tools | Vivado 2026.1 |

## Layout

| Path | Contents |
|---|---|
| `software/moonshine/` | Moonshine streaming runtime, matrix offload, native encoder and decoder exporters |
| `software/mvp/` | Citrinet runtime and transcriber |
| `software/latency/`, `software/ort_fpga_stream_branch512_neon/` | Citrinet graph passes and native operators, plus the shared FPGA transport |
| `rtl/`, `rtl/experimental/` | Microphone, MAC, bulk and branch512 RTL |
| `sim/` | Testbenches for the branch512 engine and the DSP MAC |
| `hardware/` | Microphone CDC constraints |
| `scripts/` | Setup, board wrappers, benchmarks, Vivado project and simulation scripts |
| `config/` | Source hashes, external dependency pins, policies |
| `tests/` | Host and board unit tests |
| `evidence/` | Raw board results (JSON, logs, profile) and [RESULTS.md](evidence/RESULTS.md) |
| `docs/` | [Moonshine runtime](docs/moonshine.md), [build](docs/build.md), [board setup](docs/board_setup.md), [dependencies](docs/dependencies.md), [drivers](docs/drivers.md) |

`SNAPSHOT.json` records the file hashes taken when the snapshot was made.

## Setup

Models, firmware, drivers, ONNX Runtime headers and the generated block design
are not in the repository. `scripts/setup_dependencies.py` installs them from a
pinned archive and checks every file hash. No public download URL is
configured yet; see [docs/dependencies.md](docs/dependencies.md). The Moonshine
checkpoints download from Hugging Face on first load. The native encoder and
decoder graphs are exported from them.

On the KV260, from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/setup_dependencies.py --archive /path/to/fpga-ai-accelerator-dependencies-1.0.0.zip
.venv/bin/python scripts/integrity.py
```

Then set up the Moonshine environment, export the graphs and run the final
Small profile as described in [docs/moonshine.md](docs/moonshine.md).

Host checks without external assets:

```sh
python3 scripts/integrity.py --source-only
python3 -m unittest discover -s tests -v
```

Citrinet transcription and board recovery are in
[docs/board_setup.md](docs/board_setup.md). Vivado builds, simulations and
native libraries are in [docs/build.md](docs/build.md).
