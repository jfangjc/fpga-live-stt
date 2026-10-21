# Moonshine runtime

`software/moonshine/` runs `moonshine-ai/moonshine-streaming-small` (default)
and `moonshine-ai/moonshine-streaming-tiny`. The revisions are pinned in
`software/moonshine/model.py`. The FPGA side is the 100 MHz bulk matrix engine
in the `asr-v3-mic-select` image, with the bulk `qn_tile` driver.

## Install

Use Python 3.12 on the board, in a separate environment:

```sh
python3 -m venv .venv-moonshine
.venv-moonshine/bin/pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
.venv-moonshine/bin/pip install git+https://github.com/huggingface/transformers.git@6f2e80bdad560947903bb4bde8043ae95387069a
.venv-moonshine/bin/pip install -r software/moonshine/requirements.txt
sh scripts/build_moonshine.sh
```

- **PyTorch index:** use the CPU wheel index. The default ARM64 install pulls
  CUDA libraries.
- **Model files:** the first model load downloads the pinned weights into the
  Hugging Face cache. `build/download_models.py` fetches both models ahead of
  time.
- **Transport library:** `build_moonshine.sh` builds the raw bulk transport,
  `build/native/libqnc_moonshine.so`.

## Transcribe a file

The input is mono 16 kHz audio. Each JSON line is a transcript update, and
`final: true` marks the finished utterance.

CPU reference:

```sh
PYTHONPATH=software .venv-moonshine/bin/python -m moonshine.transcribe clip.wav \
  --size small --backend cpu --chunk-ms 500 --out reports/local/moonshine-cpu.json
```

FPGA runs go through `scripts/run_moonshine_board.py`. The wrapper:
- needs an idle `k26-starter-kits` app and no loaded `qn_tile` module;
- checks the firmware and driver hashes, then loads the image and driver;
- runs the command;
- restores the starting state, even after an error or Ctrl+C;
- refuses to overwrite an existing evidence file.

```sh
sudo env PYTHONPATH=software .venv-moonshine/bin/python scripts/run_moonshine_board.py \
  --app asr-v3-mic-select --hardware-manifest build/mic-select/manifest.json \
  --driver drivers/bulk/qn_tile.ko --evidence reports/local/moonshine-session.json -- \
  .venv-moonshine/bin/python -m moonshine.transcribe clip.wav --backend fpga \
  --scope encoder-ffn --out reports/local/moonshine-fpga.json
```

Use `-` instead of a WAV path to read raw PCM16 from stdin, for example from
`arecord -q -t raw -f S16_LE -r 16000 -c 1`. For live microphone captions, see
[streaming.md](streaming.md).

Main options:

| Option | Effect |
|---|---|
| `--backend cpu`, `cpu-int8`, `oracle`, `fpga` | Float CPU, INT8 CPU, CPU integer oracle with the FPGA's arithmetic, or the physical FPGA |
| `--scope encoder-ffn` | Encoder feed-forward projections on the FPGA (default, fastest) |
| `--scope frontend-ffn`, `encoder`, `all` | Also frontend convolutions, attention, or the decoder; slower |
| `--chunk-ms` | Audio per partial update |
| `--max-tokens` | Final decoding budget (default 256) |
| `--no-draft` | Turn off reuse of the previous hypothesis |
| `--float-cpu-tail` | Use float32 instead of QNNPACK INT8 for the CPU projections |
| `--threads` | Torch threads (default 2) |

## How it works

- **Frontend:** keeps its 5 ms frame boundaries, convolution history and stride
  phase across chunks of any size.
- **Encoder:** each layer keeps only its left context and uncommitted
  lookahead, and computes only newly committed frames.
- **Decoder:** checks the previous hypothesis in one causal prefill against
  the new encoder output, then resumes decoding at the first mismatch. Partials
  get 6.5 tokens per second of audio; the final gets the full `--max-tokens`.
  A final that hits the limit is flagged as truncated.
- **INT8 arithmetic:** weights have symmetric per-row INT8 scales. Each
  projection input has one dynamic scale. Rounding is nearest-even with
  saturation to ±127.
- **Tiling:** matrices are cut into tiles of at most 1024x1024. INT32 partial
  sums are added on the ARM, then dequantized once.
- **Weight packets:** FPGA weight packets are built once at load. Each load
  only rewrites the header.
- **No fallback:** a hardware error stops the run; it does not fall back to the
  CPU.

## Native decoder and encoder

ONNX Runtime graphs replace the PyTorch decoder, and optionally the encoder
attention and convolutions. The encoder FFNs stay on the FPGA. Export once per
model into a new directory:

```sh
PYTHONPATH=software .venv-moonshine/bin/python -m moonshine.ort_decoder --size tiny --out build/tiny-decoder
PYTHONPATH=software .venv-moonshine/bin/python -m moonshine.ort_encoder --size tiny --out build/tiny-encoder
```

- **Export:** writes float and INT8 graphs plus a manifest. The runtime checks
  the manifest hashes and the model revision.
- **Pairing:** Tiny and Small artifacts cannot be mixed.

Recommended FPGA settings:

| Model | Options |
|---|---|
| Tiny | `--size tiny --threads 2 --ort-decoder build/tiny-decoder --decoder-threads 4 --chunk-ms 1000` |
| Small | `--size small --threads 4 --ort-encoder build/small-encoder --encoder-threads 4 --ort-decoder build/small-decoder --decoder-threads 4 --decoder-scheduling run-spin --chunk-ms 2500` |

For Small, also set `OMP_WAIT_POLICY=PASSIVE` in the wrapper's `sudo env`.
Use `--decoder-precision float` or `--encoder-precision float` for conformance
checks against PyTorch.

## Benchmarks

Run these inside the board wrapper.

```sh
.venv-moonshine/bin/python scripts/benchmark_moonshine.py clip.wav \
  --out-dir reports/local/moonshine-benchmark --size small --runs 3

.venv-moonshine/bin/python scripts/benchmark_moonshine_durations.py clip.wav \
  --size small --ort-decoder build/small-decoder --repeat 1 2 4 \
  --chunk-ms 2500 --decoder-threads 4 --out reports/local/small-durations.json
```

`benchmark_moonshine.py` runs these candidates:
- CPU float and CPU INT8 at 1, 2 and 4 threads;
- the integer oracle;
- the FPGA.

It checks oracle token parity, compares the texts with the float model, and
reports the speedup against the fastest CPU policy. It exits with code 2 if 2x
is missed.

`benchmark_moonshine_durations.py` repeats the clip to test longer inputs. It
exits with code 2 if any FPGA pass is slower than real time, misses the oracle,
or truncates its final.

## Tests

```sh
.venv-moonshine/bin/python -m unittest discover -s tests -p test_moonshine.py -v
```

- **`scripts/test_moonshine_physical.py`:** run it inside the wrapper before
  model tests. It checks exact INT32 output on raw tiles, and exact dequantized
  output on a 1240x2480 projection.
- **`tests/test_moonshine_checkpoint.py`:** compares encoder tensors and final
  tokens with the pinned Transformers model. Set `MOONSHINE_TEST_WAV` to a
  clip, `MOONSHINE_TEST_SIZE=tiny` for Tiny, and `MOONSHINE_TEST_ENCODER` to an
  exported encoder directory.

Upstream: [model card](https://huggingface.co/moonshine-ai/moonshine-streaming-small),
[Transformers implementation](https://github.com/huggingface/transformers/blob/6f2e80bdad560947903bb4bde8043ae95387069a/src/transformers/models/moonshine_streaming/modeling_moonshine_streaming.py).
