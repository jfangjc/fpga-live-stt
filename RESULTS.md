# Results history

All numbers are KV260 measurements. Raw data for each step is in the
`reports/local/` folder named in its heading.

How Moonshine runs were timed:
- The time is the total processing for every partial update plus finalization.
- Initialization and audio capture waits are not included.
- Each case has one untimed warmup and three measured passes. The tables give
  the median.
- "Oracle match" means the FPGA tokens equalled a CPU integer oracle with the
  same arithmetic at every update.
- Longer inputs (5 s, 10 s) repeat the same 2.5 s clip. They test scaling, not
  accuracy.

## 0. Inherited Citrinet runtime

The Citrinet-256 runtime and its `asr-v3-branch512-ab166` image come from
prototype v2: 512 pointwise MACs and 64 depthwise lanes at 166.667 MHz.
Each row is 300 paired warm runs, and all 900 full-logit comparisons matched
the CPU graph.

| Input | CPU p50 | FPGA p50 | Speedup |
|---|---:|---:|---:|
| 0.5 s | 52.130 ms | 26.114 ms | 1.996x |
| 1 s | 93.814 ms | 35.750 ms | 2.624x |
| 2.5 s | 145.449 ms | 59.443 ms | 2.447x |

`scripts/run_board.py` later passed a board smoke test: 63.191 s initialization,
36.217 ms warm median on a 1 s clip, three matching logit comparisons and a
clean rollback. Input is limited to 256 feature frames (about 2.55 s).

## 1. First Moonshine port, 20 October

`moonshine-board-20261020`

The streaming runtime in `software/moonshine/` runs the Moonshine encoder and
decoder on the CPU. The encoder feed-forward projections go to the existing
100 MHz bulk engine. Weights use per-row INT8 scales, and activations use one
dynamic scale per projection. Matrices are tiled to at most 1024x1024. Partial
INT32 sums are added on the ARM.

Physical matrix test: five raw tile shapes and a 1240x2480 projection matched
exactly (11 weight loads, 21 runs, 22 ioctls).

Results with 500 ms updates and two CPU threads (the best of 1, 2 and 4):

| Model | CPU INT8 | FPGA hybrid | CPU ÷ FPGA | Final text vs float model |
|---|---:|---:|---:|---|
| Small | 7.214 s | 7.580 s | 0.95x | Both matched |
| Tiny | 3.004 s | 3.693 s | 0.81x | Both differed |

- Both models had an oracle match.
- Neither path ran faster than real time.
- **Decoder:** on Small it took about 5.07 s of the 7.21 s CPU time. Even a
  free encoder would give at most 1.42x.
- **Transfers:** each utterance sent about 193 MB to the PL and 30 MB back,
  through 720 ioctls. The bulk engine holds one weight matrix at a time and
  pads single-token work to 16 time lanes.
- **Float paths:** both float streaming paths matched the reference
  Transformers encoder tensors and final tokens.

## 2. Tiny with an ONNX Runtime decoder, 21 October

`moonshine-tiny-performance-20261021`

The decoder moved from PyTorch/QNNPACK to an exported ONNX Runtime INT8 graph.
The encoder FFNs stayed on the FPGA.

500 ms updates, two threads:

| Path | Median | Real-time factor |
|---|---:|---:|
| FPGA hybrid, Torch decoder (step 1) | 3.693 s | 1.477 |
| FPGA hybrid, ONNX INT8 decoder | 1.640 s | 0.656 |
| CPU INT8, same ONNX decoder | 1.556 s | 0.622 |

- **Decoder time:** fell from 2.940 s to 0.885 s. Encoder time stayed at
  about 0.607 s.
- **Startup:** initialization took 19.067 s and the first pass 1.755 s.
- **Updates:** the worst measured pass was 1.646 s. The median finalization took
  0.215 s, and the slowest single update 0.462 s.
- **Transport:** 1,152 ioctls, 576 loads, 1,024 runs, 125.9 MB sent and
  31.5 MB received over the warmup and measured passes.
- **Float decoder:** the exported float decoder matched PyTorch tokens at
  every update, with logit error below 0.000057.

Longer inputs with 500 ms updates got slower than real time:

| Input | 2 decoder threads | 4 decoder threads |
|---|---:|---:|
| 2.5 s | — | 1.510 s |
| 5 s | 5.579 s | 4.918 s |
| 10 s | 14.849 s | 12.709 s |

The 0.5 s and 1 s excerpts took 0.373 s and 0.630 s, but they hit the final
token limit.

The fix was 1000 ms updates and four decoder threads. The first runs capped the
final token count by duration. They took 1.275, 2.500 and 4.761 s for 2.5, 5
and 10 s, but the 5 s final was truncated. The final policy lets finalization
use all 256 tokens:

| Input | Median | Worst pass | Real-time factor |
|---|---:|---:|---:|
| 2.5 s | 1.271 s | 1.279 s | 0.508 |
| 5 s | 2.574 s | 2.575 s | 0.515 |
| 10 s | 4.762 s | 5.105 s | 0.476 |

All passes had an oracle match and reached end-of-sequence. A fresh paired run on
2.5 s measured 1.239 s on the FPGA and 1.152 s on the CPU (0.93x). Both final
texts matched the float model on that clip.

## 3. Small with the native decoder and cached packets, 21 October

`moonshine-small-performance-20261021`

The same ONNX Runtime decoder export was applied to Small, including its
620-to-512 adapter. FPGA weight packets were prepared once at load time, so
each load only rewrites the header. That removed about 125 ms of packing per
utterance. Every projection still reloads the single FPGA weight cache.

Throughput profile: 2500 ms updates, two Torch threads, four decoder workers,
`OMP_WAIT_POLICY=PASSIVE`.

| Input | FPGA median | FPGA worst | CPU INT8 median | First FPGA pass |
|---|---:|---:|---:|---:|
| 2.5 s | 2.420 s | 2.480 s | 2.462 s | 2.846 s |
| 5 s | 4.893 s | 4.904 s | 5.068 s | 4.997 s |

With 1000 ms updates, the native decoder took 3.495 s (FPGA) against 3.513 s
(CPU) before packet caching. After caching it took 3.270 s (p95 3.307 s), still
slower than real time.

- The float decoder matched PyTorch at every update, with logit error below
  0.000156.
- A Tiny regression took 1.241 s on 2.5 s with 1000 ms updates.

## 4. Small with native encoder kernels, 21 October

`moonshine-small-2x-20261021`

Encoder attention and the two float convolutions moved to ONNX Runtime on the
ARM. The FFNs stayed on the FPGA. Other changes:
- Projection buffers use INT32 instead of INT64 when the accumulation cannot
  overflow.
- Decoder workers spin between kernels inside one call ("run-spin").
- Four threads everywhere.

| Input | Previous FPGA | New FPGA median | New FPGA worst | CPU INT8 median | CPU ÷ FPGA |
|---|---:|---:|---:|---:|---:|
| 2.5 s | 2.420 s | 1.977 s | 1.984 s | 2.270 s | 1.15x |
| 5 s | 4.893 s | 4.066 s | 4.074 s | 3.976 s | 0.98x |

- **FPGA gain:** about 1.22x faster than step 3 on 2.5 s.
- **CPU spread:** CPU passes on 2.5 s ranged from 1.943 s to 2.817 s, so the
  CPU median is not a stable bound.
- **Without run-spin:** an earlier full sweep found the CPU slightly faster
  (2.032 s vs 2.081 s).
- **1000 ms updates:** 2.62–2.68 s on 2.5 s, slower than real time.
- **Checks:** all passes had an oracle match. The float encoder matched the
  streaming reference with odd chunk sizes, with export error up to 0.000786.
- **Tiny regression:** 1.204 s on 2.5 s with 1000 ms updates.

The limit is now the CPU side. Frontend plus decoder take about 1.148 s, while
half of the fastest CPU pass is 0.972 s. A free encoder would still miss 2x.

## 5. Microphone streaming prototype, 21 October

`moonshine-streaming-prototype-20261021`, `streaming-hardware`

`moonshine.live` keeps the model loaded and runs energy-based speech detection.
It sends revisable partials, then a final for each utterance. A native helper
reads the PL microphone FIFO in 20 ms blocks.

The new image `asr-v3-mic-select` keeps the 100 MHz bulk engine. It adds a
selectable data input (primary/secondary) and I2S slot (left/right).

| Build | Value |
|---|---:|
| Setup slack | +0.653 ns |
| Hold slack | +0.012 ns |
| LUTs | 29,552 (25.2%) |
| DSPs | 577 (46.2%) |
| URAM | 64 (100%) |

Simulation covered both inputs, both slots, signed samples, FIFO backpressure,
reset and invalid configuration writes.

Microphone findings:
- **Wiring:** on the carrier, J2 is mic L and J3 is mic R. J3 showed up on the
  primary input, right slot (`--mic-select 1`): 48,000 non-zero samples in 3 s.
  The left slot was all zero.
- **Format:** the low six bits of each 24-bit sample were always zero, as
  expected for an 18-bit microphone.
- **DC offset:** about −0.094 full scale, so live capture applies a 30 Hz
  high-pass filter.
- **Quiet room:** 60 s, 960,000 samples, no errors, no false utterances,
  about −64 dBFS after filtering.

| Test | Result |
|---|---|
| 62.4 s paced replay, Small | 16 utterances, oracle match, max lag 1.83 s, queue 1.46 s |
| Capture during that replay | 65 s, 1,040,000 samples, no new drops, at most one queued block |
| Live microphone, Small | 9 utterances, captions matched the spoken audio by ear |
| Same live session | 151.5 s of audio, peak lag 5.06 s, capture queue up to 7 s |

Live recognition worked, but continuous speech piled up a backlog because
decoding is slow.

## 6. Tiny low-latency profile, 22 October

`tiny-latency-work-20261022`

`--low-latency` settings:
- Tiny's native encoder: attention on the ARM, FFNs on the FPGA.
- 250 ms updates, a 350 ms silence endpoint and 3 s utterance contexts.
- When audio is queued, intermediate partials are skipped to catch up.

62.5 s paced replay with concurrent J3 capture:

| Metric | p95 | Max |
|---|---:|---:|
| Partial lag after the last source block | 284 ms | 394 ms |
| Partial update age (includes collection and 240 ms lookahead) | 830 ms | 982 ms |
| Update age including finals | — | 1.09 s |

- **Output:** 210 partials and 22 finals, none truncated. All 232 updates had an
  oracle match.
- **Timing:** gaps between partials stayed under 470 ms, and the capture queue
  peaked at 620 ms.
- **Processing:** the real-time factor was 0.67. Initialization took 19.1 s.
- **Microphone:** no dropped samples.

The 3 s context can split words and lower accuracy.

## 7. Tiny accuracy mode, 22 October

`tiny-accuracy-work-20261022`

`--accuracy` settings:
- Keeps up to 12 s of encoded speech.
- Sends 2 s overlapping previews every 400 ms.
- When a phrase ends, re-decodes the whole phrase from the cached encoder
  features.
- After 6 s, a 250 ms pause ends the phrase; otherwise the endpoint is 700 ms
  of silence.

A 250 ms preview interval starved the final refinement on continuous speech.
400 ms leaves enough headroom.

62.5 s paced replay, 30 Hz high-pass:

| Metric | p95 | Max |
|---|---:|---:|
| Preview update age | 993 ms | 1,001 ms |
| Final lag after the endpoint | 2.24 s | 2.90 s |

- **Output:** 148 previews and 10 refined finals. All 168 updates had an
  oracle match.
- **Queues:** the refinement queue held at most one phrase, and the capture
  queue peaked at 360 ms.
- **Microphone:** concurrent J3 capture dropped no samples in 65 s.

Two synthetic conversation clips, 69 reference words:

| Variant | Word errors |
|---|---:|
| 3 s low-latency profile | 2 |
| Accuracy mode with refinement | 1 |
| Whole clip: float, FPGA INT8, float attention, float decoder | 0 each |

This set is too small to estimate WER.

## 8. Tiny CPU vs FPGA caption lag, 22 October

`tiny-cpu-fpga-comparison-20261022`

Setup:
- Accuracy mode, two 62.5 s paced trials per backend, run in CPU/FPGA/FPGA/CPU
  order.
- Same INT8 native attention and decoder, 400 ms updates and 30 Hz filter.

| Pooled p95 | CPU INT8 | FPGA hybrid | Difference |
|---|---:|---:|---:|
| Preview update age | 0.973 s | 0.987 s | +14 ms |
| Final lag after endpoint | 1.184 s | 1.440 s | +257 ms |

- All trials completed ten finals without truncation, with 280 final tokens each.
- Final captions were not identical across trials.

The FPGA hybrid did not reduce lag.

## What was learned

- **The decoder dominates:** Moonshine's autoregressive decoder takes most of
  the time and runs on the CPU. Offloading only encoder FFNs to the bulk engine
  cannot reach 2x.
- **Engine fit:** the bulk engine holds one weight matrix, reloads it for every
  projection and pads single-token work to 16 lanes. Routing decoder projections
  through it would not help.
- **CPU-side gains:** the large improvements came from the CPU: an ONNX Runtime
  decoder, native encoder kernels and thread scheduling. They speed up the CPU
  baseline as much as the hybrid.
- **What 2x would need:** decoder hardware with resident weights in
  DMA-accessible memory, a matrix-vector dataflow and grouped Q/K/V projections.
- **Microphone:** capture is reliable under inference load. Live latency is
  limited by decoding, not capture.

## Tried and rejected

- **Per-tensor INT8 frontend on the CPU:** produced an empty transcript.
- **`--scope encoder` / `all`:** single-token decoder projections pay the
  16-lane padding, so wider FPGA scopes were slower or no better. They also
  changed the partial outputs.
- **INT4 decoder:** slower than INT8 (about 2.92 s vs 2.49 s).
- **Two native encoder workers:** no gain; four helped.
- **Single-token graph specialization and dynamic-block scheduling:** small or
  negative gains.
- **Duration-capped final token budget:** truncated finals, replaced by the full
  256-token budget.
- **250 ms previews in accuracy mode:** starved final refinement.
