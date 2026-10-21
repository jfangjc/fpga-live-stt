# Results

All numbers are KV260 measurements on one 2.5 s, 16 kHz recording. Longer
inputs repeat that clip. Each time is the median cumulative processing over
all partial updates and finalization, with one untimed warmup and three
measured passes. Initialization and capture waits are excluded.

FPGA runs offload the encoder feed-forward projections (`--scope encoder-ffn`)
to the 100 MHz bulk image. Every FPGA run was checked token for token against
the integer oracle at every update.

## 1. Starting point: Torch decoder, 500 ms updates

| Model | CPU INT8 | FPGA hybrid | CPU ÷ FPGA |
|---|---:|---:|---:|
| Small | 7.214 s | 7.580 s | 0.95x |
| Tiny | 3.004 s | 3.693 s | 0.81x |

- The decoder took about 5.07 s of the Small CPU time. Encoder-only offload
  could reach at most about 1.42x.
- Small final text matched the float reference on both paths. Tiny differed.
- The FPGA run moved about 193 MB to the PL and 30 MB back per utterance,
  through 720 ioctls.

## 2. Native ONNX Runtime decoder

The autoregressive decoder moved to ONNX Runtime on ARM (`--ort-decoder`).

Tiny, 500 ms updates, two threads:

| Path | p50 | Real-time factor |
|---|---:|---:|
| FPGA hybrid, Torch decoder | 3.693 s | 1.48 |
| FPGA hybrid, ONNX INT8 decoder | 1.640 s | 0.66 |
| CPU INT8, same ONNX decoder | 1.556 s | 0.62 |

Tiny, 1000 ms updates, four decoder threads:

| Audio | FPGA p50 | Worst pass | Real-time factor |
|---|---:|---:|---:|
| 2.5 s | 1.271 s | 1.279 s | 0.51 |
| 5 s | 2.574 s | 2.575 s | 0.51 |
| 10 s | 4.762 s | 5.105 s | 0.48 |

Small, 2500 ms updates, two Torch threads, four decoder workers,
`OMP_WAIT_POLICY=PASSIVE`, cached weight packets. This is the "previous FPGA"
baseline for this snapshot:

| Audio | FPGA p50 | Worst pass | CPU INT8 p50 |
|---|---:|---:|---:|
| 2.5 s | 2.420 s | 2.480 s | 2.462 s |
| 5 s | 4.893 s | 4.904 s | 5.068 s |

- Decoder time on Tiny fell from 2.940 s to 0.885 s.
- Cached weight packets removed about 125 ms of repeated packing per Small
  utterance. Weights still reload into the single FPGA cache.

## 3. Native encoder kernels and run-spin scheduling

Attention, its projections, residual normalization and the two frontend
convolutions moved to ONNX Runtime on ARM (`--ort-encoder`). The FFNs stay on
the FPGA. Attention uses dynamic per-channel INT8 weights; the convolutions
stay float32.

CPU sweep with the native encoder, sleep scheduling, 2.5 s:

| Path | p50 |
|---|---:|
| Fastest CPU INT8 (four threads) | 2.032 s |
| FPGA hybrid (four threads) | 2.081 s |

Decoder scheduling (FPGA, `small-ort-scheduling-probe.log`, mean of three
passes):

| Scheduling | 2500 ms updates | 1000 ms updates |
|---|---:|---:|
| sleep | 2.13 s | 2.86 s |
| run-spin | 2.00 s | 2.67 s |
| run-spin, static blocks | 1.99 s | 2.65 s |

Run-spin keeps decoder workers spinning between kernels inside one `Run()`
call and stops when it returns. It was adopted for the decoder only; adding it
to the encoder gave no clear further gain.

## 4. Final Small profile

`--ort-encoder`, `--ort-decoder`, four threads everywhere,
`--decoder-scheduling run-spin`, 2500 ms updates, `OMP_WAIT_POLICY=PASSIVE`.
Data: `small-2x-final-durations.json`.

| Audio | Previous FPGA | New FPGA p50 | Worst pass | CPU INT8 p50 | CPU ÷ FPGA |
|---|---:|---:|---:|---:|---:|
| 2.5 s | 2.420 s | 1.977 s | 1.984 s | 2.270 s | 1.15x |
| 5 s | 4.893 s | 4.066 s | 4.074 s | 3.976 s | 0.98x |

- The FPGA path is about 1.22x faster than the previous FPGA version.
- The CPU passes on 2.5 s ranged from 1.943 s to 2.817 s, so the CPU median is
  not a stable lower bound. Against the fastest CPU pass, FPGA is slower.
- All FPGA updates matched the integer oracle and the earlier sleep-policy
  outputs, and reached EOS without truncation.
- With 1000 ms updates, Small still takes 2.62–2.68 s for 2.5 s of audio.

Tiny regression on the same build (1000 ms updates, `tiny-2x-regression.json`):

| Path | p50 |
|---|---:|
| FPGA hybrid | 1.204 s |
| CPU INT8 | 1.135 s |

## Citrinet-256 reference

The Citrinet runtime is unchanged from Prototype v4. Its earlier result on
`asr-v3-branch512-ab166`, 300 paired warm runs per length, all logits
bit-exact with the CPU INT8 graph:

| Audio | CPU p50 | FPGA p50 | Speedup |
|---|---:|---:|---:|
| 0.5 s | 52.130 ms | 26.114 ms | 2.00x |
| 1 s | 93.814 ms | 35.750 ms | 2.62x |
| 2.5 s | 145.449 ms | 59.443 ms | 2.45x |

## Validation

- **Host suite:** passed with 8 dependency or checkpoint skips (`host-tests.log`).
- **Board unit tests:** 14 matrix, chunk, cache and generation tests passed
  (`small-2x-final-unit.log`).
- **Physical matrix test:** raw and prepared FPGA loads, resident reuse and a
  1240x2480 tiled projection were exact.
- **Native encoder:** the float graph matched the streaming reference across
  odd chunk boundaries and EOF flush. Export error was at most 0.000786.
- **Board state:** every session restored `k26-starter-kits` with `qn_tile`
  unloaded (`small-2x-final-state.log`, `small-2x-final-apps.log`).

## What was learned

- **The CPU decoder sets the floor.** In the final profile the frontend and
  decoder alone take about 1.148 s. Half the fastest CPU pass is 0.972 s.
  Removing the whole encoder would still miss 2x.
- **Most gains came from the CPU side.** The native decoder, native encoder
  and scheduling helped both paths, so the ratio barely moved.
- **The bulk engine does not fit decoding.** It pads single-token work to 16
  time lanes, holds one weight matrix and copies weights through DMA per call.
- **A 2x design needs decoder hardware:** resident DMA-accessible weights, a
  matrix-vector dataflow, grouped Q/K/V projections and retained
  intermediates.

## Tried and rejected

- **Native encoder with two workers:** no gain. Four workers helped.
- **Wider FPGA scope** (`frontend-ffn`, `encoder`): little or no gain, and
  `frontend-ffn` changed the 1000 ms partial outputs (`small-scope-probe.log`).
- **INT4 decoder:** 2.92 s versus 2.49 s for INT8 (`small-int4-probe.log`).
- **Single-token decoder graph specialization:** small or negative gain.
- **Dynamic-block scheduling:** small or negative gain.
- **Per-tensor INT8 frontend weights:** produced an empty transcript.
- **Decoder projections on the bulk engine (`--scope all`):** single-token
  work pays the 16-lane padding cost. Not a speedup.
