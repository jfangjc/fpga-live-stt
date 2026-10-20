# Results history

All numbers are KV260 measurements. CPU and FPGA runs are randomized and
paired, and both paths get the same input, thread policy, frontend and decoder.
Unless stated otherwise, the CPU baseline is the fastest policy screened at
that stage.

- **Citrinet** timings are warm calls on a resident session. They include the
  frontend, the model and the WordPiece decoder, plus every weight load, DMA
  transfer and synchronization on the FPGA path. FPGA logits were checked bit
  for bit against an integer oracle at every stage.
- **Whisper** timings are complete CLI runs, including process start and model
  loading.

## Citrinet-256: from slower than CPU to 2x faster, 9–14 October

These stages are shared with Prototype v2. Each row is the best confirmed
result of that stage.

| Stage | Design | Input | CPU p50 | FPGA p50 | Result |
|---|---|---|---:|---:|---|
| 1. Per-layer pointwise offload | QNC2 cached engine, 256 MACs, 100 MHz | 7.435 s | 0.564 s | 1.125 s | 2.0x slower |
| 2. One ORT session, 6 operators, graph simplification | `asr-v3-bulk`, 512 MACs | 10 s | 470.3 ms | 463.5 ms | 1.4% faster |
| 3. Retained depthwise/pointwise pairs | `asr-v3-shortwide`, 32 pairs, 64 DW lanes | 1 s | 105.3 ms | 92.6 ms | 12.0% faster |
| 4. Streamed weights, adaptive DW schedule | `asr-v3-adaptive`, 100 pairs | 1 s | 95.1 ms | 54.2 ms | 43.0% faster |
| 5. 166.7 MHz timing closure | `asr-v3-branch512-ab166` | 1 s | 93.8 ms | 35.8 ms | 2.62x faster |

### 1. Per-layer pointwise offload

The existing 256-MAC QNC2 engine ran 126 of the 129 pointwise convolutions. The
rest of the graph ran as 127 separate ORT CPU sessions. The build had routed
setup slack +0.192 ns and used 11,881 LUTs, 288 DSPs and 32 URAMs.

| Version | CPU p50 | Hybrid p50 |
|---|---:|---:|
| First hybrid | 0.543 s | 1.412 s (2.6x slower) |
| NEON packing in the native host | 0.564 s | 1.125 s (2.0x slower) |

The CPU regions alone took 0.50 s and the pointwise path 0.59 s (0.37 s in
ioctls). Even a free pointwise path would have been slower than the CPU graph.

### 2. One ORT session and a fair CPU baseline

- FPGA operators became native ORT custom operators inside one session.
- The baseline moved to an ORT INT8 graph, which cut CPU time on the 10 s
  recording from 0.722 s to 0.527 s (27%).
- `asr-v3-bulk` keeps a layer's input in 1 MiB of UltraRAM and does bias
  correction and requantization on the FPGA. It closed timing at 100 MHz with
  +0.314 ns setup slack.

| Step | CPU p50 | FPGA p50 |
|---|---:|---:|
| 3 operators, 10 s | 536.9 ms | 532.4 ms |
| 6 operators, 10 s | 535.8 ms | 528.8 ms |
| Graph simplification (5,109 to 1,411 nodes), 10 s | 470.3 ms | 463.5 ms |
| Trimmed feature padding, 0.5 s | 68.8 ms | 68.5 ms |
| Trimmed feature padding, 1 s | 104.6 ms | 103.2 ms |

FPGA active time was only 8.3 ms of the 464 ms total, so more MACs could not
help. The 1,024-MAC `asr-v3-quad` build failed routing with 1,288 node overlaps.
Per-recording tables are in `reports/fused/bulk_acceptance_summary.md` and
`reports/fused/bulk_six_acceptance_summary.md`.

### 3. Retained depthwise/pointwise pairs

Each pair runs a depthwise convolution, its mask and the next pointwise
convolution on the FPGA without returning to the CPU.

| Design | 0.5 s CPU → FPGA | 1 s CPU → FPGA |
|---|---:|---:|
| `asr-v3-pair`: 1 pair | 69.4 → 69.0 ms | 105.7 → 104.5 ms |
| `asr-v3-cache`: 4 resident pairs | 69.0 → 68.1 ms | 105.0 → 102.9 ms |
| `asr-v3-shortcache`: 32 resident pairs | 69.0 → 65.9 ms | 105.3 → 101.4 ms |
| Same, tuned scheduling | 69.5 → 64.4 ms | 105.2 → 96.8 ms |
| `asr-v3-shortwide`: 64 depthwise lanes | 69.2 → 62.4 ms | 105.3 → 92.6 ms |

- From 32 pairs on, the input buffer limits inputs to 256 feature frames
  (2.55 s). Kernels 11 to 21 are supported.
- Counters showed the pointwise engine waiting for input 68% of the time,
  which is why the depthwise path was widened from 16 to 64 lanes.
- On longer inputs shortwide gained about 12.5%: 2.55 s went from 169.5 ms to
  147.7 ms.

### 4. Retained chains and streamed weights

An exact lookup table merged each dequantize, activation, mask and requantize
boundary into one step. It speeds up both paths. Values are the p50 latency
reduction against the CPU baseline.

| Design | 0.5 s | 1 s | 2.5 s |
|---|---:|---:|---:|
| `asr-v3-chain`: 32 pairs in 10 chains | 18.2% | 20.6% | 18.2% |
| `asr-v3-chain-prefetch` and shared CPU tail fusion | 15.7% | 22.0% | 20.2% |
| `asr-v3-stream`: 100 pairs, weights streamed every call | 7.4% | 32.0% | 33.7% |
| Registered DMA buffers | 19.8% | 40.0% | 39.0% |
| `asr-v3-adaptive`: adaptive depthwise schedule | 30.3% | 43.0% | 38.9% |

- **Stream:** 23 native operators cover 100 pairs and keep 77 boundaries in the
  PL. All weights are uploaded inside every timed call.
- **Registered DMA buffers:** fixed program parts stay in kernel DMA memory.
  Ioctl time on short inputs fell from about 29 ms to 21 ms.
- **Adaptive schedule:** with at most 16 frames, the 64 depthwise MACs work
  across four channels instead of across time.

Adaptive result: CPU 55.9 / 95.1 / 149.9 ms, FPGA 38.9 / 54.2 / 91.6 ms.

### 5. 166.7 MHz timing closure

The 1,024-MAC residual design was congested (199,929 overlapping nodes) and was
dropped. 150 MHz was not reachable from the PS clock divider, so the target
became 166.667 MHz. Each failed build removed its worst path:

| Build | Change | Routed setup slack |
|---|---|---:|
| `pipe166` | Elastic register before requantization | −3.073 ns |
| `slice166` | Register before the pointwise input; legacy voice MAC removed | −0.536 ns |
| `outslice166` | Elastic output register | −0.075 ns |
| `drop166` | Depthwise quantizer pipeline split | −0.034 ns |
| `guard166` | Redundant header multiplier removed | 0.000 ns |
| `ab166` | DSP48E2 product register moved to the A/B input registers | **+0.043 ns** |

Software variants measured on the `ab166` image (300 pairs per input; speedup
is against the CPU measured in the same run):

| Variant | 0.5 s | 1 s | 2.5 s |
|---|---:|---:|---:|
| Base | 1.87x | 2.32x | 2.13x |
| Two scale-changing pairs retained (`scale`) | 1.91x | 2.40x | 2.20x |
| Three more pointwise tails retained (`more`) | 1.92x | 2.52x | 2.31x |
| NEON output unpacking (`neon`) | 1.96x | 2.61x | 2.43x |
| Faster exact CPU mask tails (`maskfast`) | 2.06x | 2.59x | 2.34x |
| `neon` + `maskfast` | 2.06x | 2.68x | 2.45x |
| `neon` + `maskfast` with DMA interrupt core screened (`irq`) | 2.05x | 2.67x | 2.44x |
| Exact valid-frame frontend (`vf`), selected | 2.09x | 2.62x | 2.47x |

The selected `vf` variant drops unused frontend padding on both paths. Against
the fastest CPU policy measured in any run, it is the final result:

| Input | Best CPU p50 | FPGA p50 | Speedup | CPU p95 | FPGA p95 |
|---|---:|---:|---:|---:|---:|
| 0.5 s | 52.575 ms | 26.136 ms | 2.01x | 60.090 ms | 26.993 ms |
| 1 s | 93.814 ms | 35.833 ms | 2.62x | 96.833 ms | 49.226 ms |
| 2.5 s | 145.449 ms | 58.975 ms | 2.47x | 148.425 ms | 65.061 ms |

- Each timed FPGA call makes 24 ioctls and 256 weight updates.
- All 900 warm full-logit comparisons matched the CPU.
- The audit is `reports/fused/FPGA_ASR_2X_COMPLETION_AUDIT.json`.

Final image resources: 68,136 LUTs, 37,767 registers, 83.5 BRAM tiles, 16 URAM
and 577 DSPs.

### Citrinet accuracy

There is only a diagnostic check, not a representative corpus:
- Nine recordings (the user recording, three synthetic level and noise variants
  of it, and five LibriSpeech clips). CPU and FPGA both made 24 errors in
  269 words.
- Designs from 32 pairs on accept at most 2.55 s. They were checked on 36 short
  slices of the same recordings: logits, lengths and text matched the CPU.
- On the five LibriSpeech clips, FP32 made 3 errors in 157 words and ORT INT8
  made 4.

## MVP packaging, 15 October

The final design was packaged as `kv260-asr-mvp`. It transcribes one 16 kHz
mono WAV of 0.02 to 2.56 s, switching the board to the branch image and back to
the bulk image afterwards. See [software/mvp/README.md](software/mvp/README.md).

The clean-install test used a new directory, a new virtual environment and
freshly installed branch firmware. It found two bugs, fixed in 1.0.1:
- The deployment bundle missed a log that the NEON proof depends on.
- The CLI expected the warm count of 24 ioctls on a cold session. A cold call
  also registers 24 programs, so it makes 48.

Cold CLI runs, each with 128 physical calls and 256 weight updates:

| WAV | Session setup | Cold processing |
|---|---:|---:|
| 0.5 s | 109.303 s | 93.275 ms |
| 1 s | 109.596 s | 113.043 ms |
| 2.5 s | 109.449 s | 137.428 ms |

A 2.56 s input was rejected and the board was restored. Warm retest, 300 pairs
per input, against the fastest CPU from this run or earlier evidence:

| Input | Best CPU p50 | FPGA p50 | Speedup | CPU p95 | FPGA p95 |
|---|---:|---:|---:|---:|---:|
| 0.5 s | 52.130 ms | 26.114 ms | 1.996x | 55.867 ms | 26.822 ms |
| 1 s | 93.814 ms | 35.750 ms | 2.624x | 96.833 ms | 51.011 ms |
| 2.5 s | 145.449 ms | 59.443 ms | 2.447x | 148.425 ms | 69.714 ms |

The 0.5 s case misses 2x by a hair (49.9% lower latency). Evidence is in
`reports/mvp/clean_board_test.json`.

A second install from the separate source distribution (built by
`scripts/prepare_github_folder.py`) used its own runner and shipped CPU
policies. 300 pairs per input, 10 warmup pairs:

| Input | CPU p50 | CPU p95 | FPGA p50 | FPGA p95 | Speedup |
|---|---:|---:|---:|---:|---:|
| 0.5 s | 53.912 ms | 69.047 ms | 26.202 ms | 28.507 ms | 2.058x |
| 1 s | 94.609 ms | 118.396 ms | 35.943 ms | 53.574 ms | 2.632x |
| 2.5 s | 145.651 ms | 165.493 ms | 59.241 ms | 71.904 ms | 2.459x |

All 900 output tensors matched the CPU. Its startup took 63.945 s and the first
physical call 11.346 s. Data and harness are in `reports/mvp/deployment-20261015/`.

The kernel log showed device-tree overlay-removal warnings about possible
memory leaks. They did not affect inference or rollback.

## Whisper on the bulk engine, 17–20 October

The goal changed to live voice-to-text, so Whisper was tried next. It runs on
pinned whisper.cpp v1.8.3 with a hook that sends matrix products to the
unchanged `asr-v3-bulk` image at 100 MHz:
- **FPGA:** encoder dense layers, encoder QK and AV attention, decoder
  cross-attention K/V projections. Tiles are at most 1024 x 1024, with dynamic
  INT8 quantization and FP32 accumulation of INT32 partial sums.
- **CPU:** frontend, convolutions, LayerNorm, GELU, softmax, residuals and
  autoregressive decoding.

The CPU comparator is the fastest of FP16, Q8_0 and Q5_0 (Q8_0 every time).
Both paths use four threads, English greedy decoding and unfused attention,
which was faster than fused attention on the Cortex-A53. Each clip was run
three times per configuration. Accuracy is a separate ten-speaker
LibriSpeech test-clean sample of 244 words, scored against FP16 CPU.

| Model | Audio | CPU p50 | Hybrid p50 | Speedup | Hybrid ÷ audio length |
|---|---:|---:|---:|---:|---:|
| base | 3.505 s | 16.854 s | 6.777 s | 2.49x | 1.93 |
| base | 14.225 s | 18.209 s | 8.162 s | 2.23x | 0.57 |
| base | 23.315 s | 19.093 s | 9.103 s | 2.10x | 0.39 |
| small | 3.505 s | 58.403 s | 19.507 s | 2.99x | 5.57 |
| small | 14.225 s | 61.617 s | 22.721 s | 2.71x | 1.60 |
| small | 23.315 s | 63.820 s | 24.866 s | 2.57x | 1.07 |
| large-v3-turbo | 3.505 s | 338.440 s | 116.487 s | 2.91x | 33.23 |
| large-v3-turbo | 14.225 s | 338.107 s | 110.004 s | 3.07x | 7.73 |
| large-v3-turbo | 23.315 s | 335.387 s | 95.688 s | 3.50x | 4.10 |

| Model | FP16 CPU errors | Hybrid errors | FPGA work per English pass |
|---|---:|---:|---|
| base | 11/244 | 11/244 | 60 matrix calls, 12 attention calls, 252 weight loads |
| small | 5/244 | 5/244 | 120 matrix calls, 24 attention calls, 720 weight loads |
| large-v3-turbo | 7/244 | 6/244 | 264 matrix calls, 64 attention calls, 3,744 weight loads |

For base, Q8_0 CPU also made 11 errors and Q5_0 15. The small and turbo
measurements pre-read the model file before each run.

### Why the times are so long

A timing audit reran turbo on the 3.505 s clip under GNU `time`:

| Build | Wall time | Model load | Encoder |
|---|---:|---:|---:|
| CPU, generic ARM build | 316.11 s | 2.176 s | 312.218 s |
| CPU, native Cortex-A53 tuned | 315.40 s | 2.196 s | 311.602 s |
| FPGA hybrid | 93.23 s | 2.197 s | 89.160 s |

- No unit error: all 36 saved runs agreed with whisper.cpp's own totals within
  0.827 s. Native CPU tuning gained 0.2%.
- whisper.cpp always encodes the full 1500-position (30 s) window and pads
  short input with zeros, so encoder time is the same for every clip.
- Turbo still has 32 encoder layers; only its decoder is small.
- In the hybrid run, FPGA hooks took 69.9 s, of which 44.0 s was in driver
  calls. Activation scanning, request packing and output unpacking took 4.3,
  7.3 and 8.0 s. One pass made 8,880 ioctls and moved 3.663 GB to the FPGA and
  11.587 GB back.
- Peak hybrid memory was 1.73 GiB for turbo and 602 MiB for small.

The small hybrid encoder takes about 17 s per clip. Its token decoding grows
with transcript length, from 0.82 s to 5.75 s.

A replay of the base benchmark on 20 October reproduced the old medians within
0.6–1.6% (CPU 16.953 / 18.316 / 19.241 s, hybrid 6.885 / 8.252 / 9.181 s). Base
on the newer small-model backend gave hybrid 6.633 / 8.086 / 8.963 s. So the OS
had not slowed down; the larger models are simply more work.

### Decision

All three models pass the 2x gate on fixed files, but none is usable for live
captions on this design. Even small needs about 17 s of encoder time per update,
so a live queue would grow without bound. A live design would need a shorter
encoder context or a streaming model, with the model and FPGA session kept
resident. The recommended next candidate was Moonshine Streaming (Tiny, then
Small), which encodes audio incrementally. It was not benchmarked here.

## What was learned

- **Boundaries cost more than MACs.** Per-layer offload lost to the CPU, and
  doubling MACs did nothing while the engine was idle 98% of the time. Speed came
  from keeping whole blocks on the FPGA and cutting ioctls and host work.
- **Make the CPU baseline strong first.** INT8, graph simplification, exact
  lookup tails and policy screens sped up the CPU too, and every FPGA gain was
  measured against that faster baseline.
- **Timing closure is incremental.** Six builds, each fixing one critical
  path, took the design from −3.073 ns to +0.043 ns at 166.7 MHz.
- **Relative speedup is not live usability.** Whisper passed 2x but stayed far
  slower than real time because of the fixed 30 s encoder window.

## Tried and rejected

- **Sparse mel frontend:** same accuracy, but the frontend got slower.
- **Fixed graph shapes, frozen lengths:** no gain.
- **Prepacked weights on the bulk engine:** less host work, no significant
  end-to-end gain.
- **Residual overlap and pipeline worker variants**
  (`software/ort_fpga_overlap*`, `software/ort_fpga_pipeline*`): no reliable gain.
- **1,024-MAC engines** (`asr-v3-quad` and the residual branch design): failed
  routing.
- **Longer DMA bursts (16 to 128 beats) at 166.7 MHz:** setup −0.308 ns; a
  post-route repair reached −0.258 ns. Not deployed.
- **Incremental Vivado implementation:** not covered by the installed license.
- **Reciprocal quantizer in the CPU tail:** bit-exact, but no faster.
- **Whisper decoder on the FPGA (`--fpga-decoder`):** made transcription slower.
