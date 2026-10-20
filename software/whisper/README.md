# Whisper on the bulk FPGA engine

A patch for whisper.cpp v1.8.3 (commit `2eeeba56`) that sends large matrix
products to the `asr-v3-bulk` image at 100 MHz. Supported models are
multilingual `base`, `small` and `large-v3-turbo` (`model_spec.py`).

- **FPGA:** encoder dense layers, encoder QK/AV attention per head and decoder
  cross-attention K/V projections. Tiles are at most 1024 x 1024; activations
  and weights are quantized to INT8 on the fly and INT32 partial sums are
  accumulated in FP32 on the CPU.
- **CPU:** frontend, convolutions, LayerNorm, GELU, softmax, residuals and
  autoregressive decoding.
- A failed FPGA operation aborts the run. One inference per process, one
  hardware client at a time.

| File | Purpose |
|---|---|
| `patch_upstream.py`, `kv260-direct.h`, `qnc_ggml.inc` | Matrix hook and DMA packing inserted into whisper.cpp |
| `build_board.sh` | Clones whisper.cpp, builds CPU and hybrid CLIs, downloads and quantizes the model |
| `run_board.py` | One WAV, with app activation and restore |
| `hardware_session.py` | Runs any command with the bulk app loaded, then restores `k26-starter-kits` |
| `benchmark.py` | Randomized paired CPU/hybrid CLI benchmark |
| `evaluate_report.py` | WER from saved transcripts |
| `qualify.py`, `qualify_board.py`, `evaluate_small_board.py` | Turbo and small qualification runs |
| `audit_timing.py`, `audit_base_os.py` | Timing audit and base replay |
| `test_physical_matrix.py`, `test_benchmark.py` | Physical arithmetic conformance and claim checks |
| `verify_runtime.py` | Checks an unpacked runtime against its manifest |

## Build and run on the board

The board must start in `k26-starter-kits` with no `qn_tile` module. `--release`
points to a directory holding the installed bulk firmware and its driver at
`deployment/kernel-compat/<kernel>/bulk/qn_tile.ko`.

```sh
mkdir ~/whisper-work && cd ~/whisper-work
sh /path/to/project/software/whisper/build_board.sh /path/to/project "$PWD" large-v3-turbo
sudo python3 /path/to/project/software/whisper/run_board.py /absolute/path/clip.wav \
  --work "$PWD" --release /path/to/release \
  --model "$PWD/models/ggml-large-v3-turbo-q8_0.bin" --language en --out reports/transcript.json
```

Use `base` or `small` instead of `large-v3-turbo` for the other models. Input
must be 16 kHz mono PCM WAV.

## Benchmark

```sh
sudo python3 /path/to/project/software/whisper/hardware_session.py \
  --release /path/to/release --expected-app k26-starter-kits --evidence session.json -- \
  python3 /path/to/project/software/whisper/benchmark.py \
    --cpu build-cpu/bin/whisper-cli --hybrid build-hybrid/bin/whisper-cli \
    --model models/ggml-base-q8_0.bin --cpu-model models/ggml-base.bin \
    --cpu-model models/ggml-base-q8_0.bin --cpu-model models/ggml-base-q5_0.bin \
    --audio clip.wav --fpga-attention --cpu-unfused-only --repeats 3 --warmup 1 --out results
python3 software/whisper/evaluate_report.py results/results.json --manifest research/whisper-validation/evaluation.jsonl --out wer.json
```

Timing includes process start and model loading; app activation is recorded
separately. Results are in [RESULTS.md](../../RESULTS.md#whisper-on-the-bulk-engine-1720-october).
