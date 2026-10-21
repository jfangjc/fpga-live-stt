# Moonshine runtime

`software/moonshine/` runs `moonshine-ai/moonshine-streaming-small` (default)
or `moonshine-ai/moonshine-streaming-tiny`. Revisions are pinned in
`software/moonshine/model.py`.

The FPGA path uses the existing `asr-v3-bulk` image, its `qn_tile` driver and
`software/ort_fpga_stream_branch512_neon/qnc_transport.c`. It does not use the
Citrinet branch image.

## Install

On the board, with Python 3.12. Install the dependency archive first
([dependencies.md](dependencies.md)) so the bulk firmware and driver are present.

```sh
python3 -m venv .venv-moonshine
.venv-moonshine/bin/pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
.venv-moonshine/bin/pip install git+https://github.com/huggingface/transformers.git@6f2e80bdad560947903bb4bde8043ae95387069a
.venv-moonshine/bin/pip install -r software/moonshine/requirements.txt
sh scripts/build_moonshine.sh
```

- Use the CPU wheel index. The default ARM64 PyTorch wheel pulls CUDA libraries.
- `scripts/build_moonshine.sh` builds `build/native/libqnc_moonshine.so`.
- The first model load downloads the pinned checkpoint from Hugging Face.

Export the native graphs once. Each needs a new output directory:

```sh
PYTHONPATH=software .venv-moonshine/bin/python -m moonshine.ort_decoder --size small --out build/small-decoder
PYTHONPATH=software .venv-moonshine/bin/python -m moonshine.ort_encoder --size small --out build/small-encoder
```

Exports write float and INT8 graphs with a manifest of hashes and the model
revision. The runtime refuses graphs from another model or revision.

## Run

CPU reference:

```sh
PYTHONPATH=software .venv-moonshine/bin/python -m moonshine.transcribe clip.wav \
  --size small --backend cpu --out reports/local/moonshine-cpu.json
```

FPGA hybrid, final Small profile. `scripts/run_moonshine_board.py` needs an idle
`k26-starter-kits` app with no `qn_tile` module loaded. It checks the bulk
firmware and driver hashes, loads the bulk image, runs the command and restores
the original state. The driver path is the one installed by
`scripts/setup_dependencies.py`. Use a new evidence path for every session.

```sh
sudo env OMP_WAIT_POLICY=PASSIVE PYTHONPATH=software .venv-moonshine/bin/python scripts/run_moonshine_board.py \
  --driver drivers/prebuilt/6.8.0-1036-xilinx/bulk/qn_tile.ko \
  --evidence reports/local/small-session.json -- \
  .venv-moonshine/bin/python -m moonshine.transcribe clip.wav --size small \
  --backend fpga --scope encoder-ffn --threads 4 --chunk-ms 2500 \
  --ort-encoder build/small-encoder --encoder-threads 4 \
  --ort-decoder build/small-decoder --decoder-threads 4 \
  --decoder-scheduling run-spin --runs 3 --out reports/local/small-fpga.json
```

- Input is mono 16 kHz. Use `-` instead of a WAV path for raw PCM16 on stdin,
  for example from `arecord -q -t raw -f S16_LE -r 16000 -c 1`.
- Output is one JSON line per transcript update. `final: true` marks the end.
- WAV runs do one untimed warmup by default (`--warmup`).
- Utterances are limited to 30 s (`--max-seconds`). There is no VAD.
- A hardware error is raised. There is no CPU fallback.

Main options of `moonshine.transcribe`:

| Option | Meaning |
|---|---|
| `--backend cpu\|cpu-int8\|oracle\|fpga` | Float CPU, QNNPACK INT8 CPU, integer oracle on CPU, or physical FPGA |
| `--scope encoder-ffn` | FPGA runs encoder FFNs (default). `frontend-ffn`, `encoder` and `all` widen the scope. |
| `--chunk-ms` | Update interval (default 500) |
| `--ort-decoder`, `--ort-encoder` | Use exported native graphs |
| `--decoder-precision`, `--encoder-precision` | `int8` (default) or `float` for conformance checks |
| `--decoder-scheduling`, `--encoder-scheduling` | `sleep` (default) or `run-spin` |
| `--max-tokens` | Final decoding budget (default 256) |
| `--no-draft` | Regenerate each partial instead of verifying the previous hypothesis |
| `--float-cpu-tail` | Float32 instead of QNNPACK INT8 for projections left on the CPU |

## How it works

- **Streaming state:** the frontend keeps 5 ms frame boundaries, convolution
  history and stride phase across chunks. Each encoder layer keeps only its
  left context and uncommitted lookahead. Finalization drains the lookahead.
- **Decoding:** each update verifies the previous hypothesis in one causal
  prefill and resumes at the first disagreement. Partial updates get 6.5 tokens
  per second of audio. Finalization gets the full `--max-tokens` budget.
- **Quantization:** symmetric per-row INT8 weights, one dynamic INT8 scale per
  projection input, round-to-nearest-even, saturation to ±127.
- **Tiling:** matrices are split into tiles of at most 1024 x 1024. Partial
  INT32 sums are added on ARM, then dequantized once with the whole-projection
  scales. Accumulation is INT32 when `K*127*127` fits and INT64 otherwise.
- **Weight packets:** FPGA weight packets are built once at model load. Weights
  still reload into the single FPGA cache for each projection.
- **Oracle:** `--backend oracle` does the same integer arithmetic on CPU. It is
  a correctness check, not a timing baseline. Compare oracle and FPGA with the
  same draft policy and graphs, because dynamic scales depend on batch shape.

## Benchmarks

Run inside the board wrapper, as above.

Paired CPU versus FPGA. It sweeps CPU float and INT8 at 1, 2 and 4 threads,
runs the oracle and the FPGA, and exits 2 if the 2x target is missed:

```sh
.venv-moonshine/bin/python scripts/benchmark_moonshine.py clip.wav \
  --out-dir reports/local/moonshine-benchmark --size small --runs 3 \
  --ort-decoder build/small-decoder --ort-encoder build/small-encoder
```

Duration scaling. It loads each model once and runs the clip repeated 1, 2
and 4 times. It exits 2 if any FPGA pass is slower than the audio, misses
oracle parity or truncates the final output:

```sh
.venv-moonshine/bin/python scripts/benchmark_moonshine_durations.py clip.wav \
  --size small --ort-decoder build/small-decoder --ort-encoder build/small-encoder \
  --threads 4 --chunk-ms 2500 --decoder-scheduling run-spin \
  --out reports/local/small-durations.json
```

Both accept `--size tiny` with Tiny graphs.

## Tests

```sh
.venv-moonshine/bin/python -m unittest discover -s tests -p test_moonshine.py -v
```

- `scripts/test_moonshine_physical.py --out <json>` runs inside the board
  wrapper. It checks exact INT32 output on raw tiles and a 1240x2480 projection.
- `tests/test_moonshine_checkpoint.py` compares against the pinned
  Transformers model. Set `MOONSHINE_TEST_WAV` to a 16 kHz mono clip.
  `MOONSHINE_TEST_ENCODER` and `MOONSHINE_TEST_DECODER` point it at exported
  graphs. `MOONSHINE_TEST_SIZE` selects `small` or `tiny`.

Results are in [../evidence/RESULTS.md](../evidence/RESULTS.md).
