# KV260 speech-to-text accelerator, prototype v4

Streaming speech recognition with Moonshine on the Kria KV260. Moonshine
streaming-tiny and streaming-small run on the ARM CPU. Their encoder
feed-forward projections run on the INT8 bulk matrix engine from the earlier
Citrinet work. The repository also has a live microphone prototype with
selectable I2S inputs. The Citrinet-256 runtime from prototype v2 is kept as well.

This repository holds the v4 iteration (20–22 October 2026).

## Results

Moonshine timing is the total processing time for every partial update plus
finalization, on the 2.5 s test clip. Initialization and capture waits are not
included. Each row has one warmup and three measured passes. On every FPGA pass,
the tokens matched an integer oracle at each update.

| Model and profile | Updates | CPU INT8 median | FPGA hybrid median | CPU ÷ FPGA |
|---|---:|---:|---:|---:|
| Tiny, first port (Torch decoder) | 500 ms | 3.004 s | 3.693 s | 0.81x |
| Tiny, ONNX Runtime INT8 decoder | 1000 ms | 1.152 s | 1.239 s | 0.93x |
| Small, first port (Torch decoder) | 500 ms | 7.214 s | 7.580 s | 0.95x |
| Small, native encoder and decoder kernels | 2500 ms | 2.270 s | 1.977 s | 1.15x |

Tiny with 1000 ms updates processed 2.5, 5 and 10 s inputs in 1.271, 2.574 and
4.762 s, which is under the recording length in each case. The 5 s and 10 s
inputs repeat the 2.5 s clip.

Live streaming, all on Tiny with the FPGA hybrid unless noted:

| Test | Result |
|---|---|
| `--low-latency` profile, 62.5 s paced replay | Partial update age 0.83 s p95, 0.98 s max; all 232 updates matched the oracle |
| `--accuracy` profile, 62.5 s paced replay | Preview age 0.99 s p95; final lag 2.24 s p95 after the endpoint |
| CPU vs FPGA in accuracy mode, p95 | Preview age 0.973 s vs 0.987 s; final lag 1.184 s vs 1.440 s |
| Small, live microphone on J3 | 9 utterances, captions confirmed by ear; lag up to 5.06 s |
| Capture during FPGA inference | 65 s, 1,040,000 samples, no FIFO drops |

The 2x FPGA-versus-CPU target was not met. Most of the time is in the
autoregressive decoder, which runs on the CPU. Accuracy was only checked on a few
clips; there is no held-out WER. [RESULTS.md](RESULTS.md) has the full history.

## Hardware and software

- **Board:** AMD Kria KV260, Ubuntu with kernel `6.8.0-1036-xilinx`, Python 3.12.
- **Tools:** Vivado 2026.1, part `xck26-sfvc784-2LV-c`, board `xilinx.com:kv260_som:part0:2.0`.
- **Moonshine image (`asr-v3-mic-select`):** the 100 MHz bulk INT8 matrix engine
  with 1024x1024 tiles, plus a microphone receiver with selectable data input and
  I2S slot. Routed setup slack +0.653 ns, hold +0.012 ns. It uses 29,552 LUTs,
  577 DSPs and all 64 URAMs.
- **Citrinet image (`asr-v3-branch512-ab166`):** 512 pointwise MACs and 64
  depthwise lanes at 166.667 MHz, carried over from prototype v2.
- **Models:** `moonshine-ai/moonshine-streaming-tiny` and
  `moonshine-ai/moonshine-streaming-small`, with revisions pinned in
  `software/moonshine/model.py`. Citrinet uses `nvidia/stt_en_citrinet_256_ls`.
- **Driver:** the `qn_tile` character driver on the Linux AXI DMAengine. XRT is
  not used.

## Layout

| Path | Contents |
|---|---|
| `software/moonshine/` | Moonshine streaming runtime: INT8 tiling, FPGA transport, ONNX Runtime encoder/decoder export, live capture, WER scoring |
| `software/mvp/`, `software/latency/`, `software/ort_fpga_stream_branch512_neon/` | Citrinet runtime, graph transforms and ORT custom operators |
| `rtl/` | Microphone and MAC RTL; `rtl/experimental/` has the bulk, branch512 and streaming designs |
| `sim/` | Testbenches for the MAC, the branch512 engine and streaming capture |
| `hardware/` | Reference block design, top level and constraints |
| `firmware/` | Device-tree sources, `boot.bif` and `shell.json` for the bulk and branch512 apps |
| `drivers/` | `qn_tile` driver sources for the bulk and branch protocols |
| `scripts/` | Vivado builds, simulations, board wrappers, benchmarks and setup |
| `build/` | Hand-written board job and probe scripts, and the staged streaming firmware records |
| `tests/` | Host and board unit tests |
| `reports/local/` | Raw board results, logs and timing reports for every run |
| `config/` | Source hashes, policies and the old dependency manifest |
| `third_party/` | License texts; see [third_party/README.md](third_party/README.md) |

## Missing binaries

All binaries were removed before publication: bitstreams, `.dtbo` overlays,
`.ko` modules, native libraries, ONNX Runtime headers and model files.
`scripts/setup_dependencies.py` and `config/dependencies.json` describe the
archive `fpga-ai-accelerator-dependencies-1.0.0.zip`, which used to provide
them. That archive is not published and has no download URL.

| Item | How to get it |
|---|---|
| Driver sources, reference block design, licenses | Already in the tree |
| `qn_tile.ko` modules | `make -C drivers/bulk` and `make -C drivers/branch` on the board |
| Moonshine image | `scripts/project_streaming.tcl`, then `scripts/package_streaming.py` |
| Citrinet branch image | `scripts/project.tcl`, then bootgen with `firmware/asr-v3-branch512-ab166/boot.bif` |
| Moonshine models | Downloaded from Hugging Face on first load, or ahead of time with `build/download_models.py` |
| Citrinet INT8 graph | Only came from the archive; no script here re-creates it |
| ONNX Runtime 1.30.0 C headers | Copy into `software/ort_fpga_stream_branch512_neon/include/` |

The board scripts still check the old pinned hashes:

- `scripts/run_moonshine_board.py` compares the driver with the
  `drivers/prebuilt/<kernel>/bulk/qn_tile.ko` entry in `config/dependencies.json`.
  After a rebuild, write the new module's SHA256 there.
- `scripts/integrity.py` and `scripts/check_distribution.py` expect the old
  archive layout. They fail on this tree until `config/assets.json` is rewritten
  with `scripts/write_manifest.py`.

## Set up and run Moonshine

On the KV260:

```sh
python3 -m venv .venv-moonshine
.venv-moonshine/bin/pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
.venv-moonshine/bin/pip install git+https://github.com/huggingface/transformers.git@6f2e80bdad560947903bb4bde8043ae95387069a
.venv-moonshine/bin/pip install -r software/moonshine/requirements.txt
sh scripts/build_moonshine.sh
sh scripts/build_moonshine_capture.sh
make -C drivers/bulk
```

Build and install the microphone image as described in
[docs/streaming.md](docs/streaming.md). Then run a WAV file through the board
wrapper, which loads the image and restores the starting app on exit:

```sh
sudo env PYTHONPATH=software .venv-moonshine/bin/python scripts/run_moonshine_board.py \
  --app asr-v3-mic-select --hardware-manifest build/mic-select/manifest.json \
  --driver drivers/bulk/qn_tile.ko --evidence reports/local/session.json -- \
  .venv-moonshine/bin/python -m moonshine.transcribe clip.wav --size tiny \
  --backend fpga --scope encoder-ffn --out reports/local/tiny.json
```

More detail:

- [docs/moonshine.md](docs/moonshine.md): runtime options, native decoder and
  encoder export, benchmarks and tests.
- [docs/streaming.md](docs/streaming.md): microphone image, live captions, the
  Tiny latency and accuracy modes, WER scoring.
- [docs/build.md](docs/build.md): Vivado builds, simulations, drivers, board
  recovery and the Citrinet runtime.

Host unit tests, after `pip install -r requirements.txt`:

```sh
python -m unittest discover -s tests -v
```

Tests that need Torch, the checkpoint or the board skip themselves.
