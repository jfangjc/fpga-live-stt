# Results history

All numbers are KV260 measurements of warm, resident inference. Each timed
call includes:
- the audio frontend, the model and the WordPiece decoder;
- on the FPGA path, every weight load, DMA transfer and synchronization.

CPU and FPGA runs are randomized and paired, and both paths use the same input
and worker policy. Unless stated otherwise, the CPU baseline is the fastest
policy screened at that stage. Every stage also checked FPGA output bit for
bit against an integer oracle.

## 1. Per-layer pointwise offload, 9 October

The first v2 design used the existing 256-MAC QNC2 cached engine at 100 MHz.
It offloaded 126 of the model's 129 pointwise convolutions, and the remaining
operators ran on the CPU as 127 separate ORT sessions.

The build had routed setup slack +0.192 ns and used 11,881 LUTs, 288 DSPs and
32 URAMs.

Results on the 7.435 s reference clip:

| Version | CPU p50 | Hybrid p50 |
|---|---:|---:|
| First hybrid | 0.543 s | 1.412 s (2.6x slower) |
| NEON packing in the native host | 0.564 s | 1.125 s (2.0x slower) |

Where the hybrid's time went:
- CPU regions took 0.50 s.
- The pointwise path took 0.59 s, of which 0.37 s was inside ioctls.

Even making the whole pointwise path free would still leave the hybrid slower
than the CPU-only graph. The per-session fallback and the per-layer round trips
were the problem, not MAC throughput.

## 2. One ORT session and a faster CPU baseline, 10 October

Two changes:
- FPGA operators became native ORT custom operators inside a single session.
- The baseline moved to a real ORT INT8 graph. That alone cut CPU time on the
  10 s recording from 0.722 s to 0.527 s (27%).

`asr-v3-bulk` added a 512-MAC pointwise engine. It keeps each layer's input in
1 MiB of UltraRAM and does the bias correction and requantization on the FPGA.

| Step | CPU p50 | FPGA p50 |
|---|---:|---:|
| 3 offloaded operators, 10 s recording | 536.9 ms | 532.4 ms |
| 6 offloaded operators, 10 s recording | 535.8 ms | 528.8 ms |
| Graph simplification, 10 s recording | 470.3 ms | 463.5 ms |
| Trimmed padding, 0.5 s | 68.8 ms | 68.5 ms |
| Trimmed padding, 1 s | 104.6 ms | 103.2 ms |

- **Graph simplification** shared duplicate constants and removed duplicate
  operations, taking the graph from 5,109 to 1,411 nodes. It speeds up both
  paths.
- **The engine was mostly idle:** FPGA active time was only 8.3 ms of the
  464 ms total, so more MACs could not help.
- **The 1,024-MAC engine** (`asr-v3-quad`) failed routing with 1,288 node
  overlaps.

The next step had to keep whole blocks on the FPGA.

## 3. Retained depthwise and pointwise pairs, 10–11 October

Each pair runs a depthwise convolution, its mask and the following pointwise
convolution on the FPGA. The intermediate activations never return to the CPU.

| Design | 0.5 s CPU → FPGA p50 | 1 s CPU → FPGA p50 |
|---|---:|---:|
| `asr-v3-pair`: 1 pair | 69.4 → 69.0 ms | 105.7 → 104.5 ms |
| `asr-v3-cache`: 4 resident pairs | 69.0 → 68.1 ms | 105.0 → 102.9 ms |
| `asr-v3-shortcache`: 32 pairs | 69.0 → 65.9 ms | 105.3 → 101.4 ms |
| Same, tuned scheduling | 69.5 → 64.4 ms (7.3%) | 105.2 → 96.8 ms (7.9%) |
| `asr-v3-shortwide`: 64 depthwise lanes | 69.2 → 62.4 ms (9.9%) | 105.3 → 92.6 ms (12.0%) |

- **One pair:** the pair itself got faster (0.81 → 0.54 ms), but the
  whole-model gain was within noise.
- **Resident weights:** the four-pair and 32-pair designs keep their weights
  on the FPGA between calls, so a warm call does no weight loads.
- **32 pairs:** supports depthwise kernels 11 to 21. Its input buffer limits
  inputs to 256 feature frames (2.55 s).
- **64 depthwise lanes:** counters showed the pointwise engine waiting for
  input 68% of the time, so the depthwise path was widened from 16 to 64 lanes.

With the 32-pair graph, longer inputs gained about 12.5%. The 2.55 s input
went from 169.5 ms to 147.7 ms.

## 4. Retained chains and streamed weights, 12 October

The target was first a 20% reduction and later 2x. An exact lookup table now
merges each dequantize, activation, mask and requantize boundary into one step.
It applies to both paths, so the CPU baseline got faster too.

| Design | 0.5 s | 1 s | 2.5 s |
|---|---:|---:|---:|
| `asr-v3-chain`: 32 pairs in 10 chains | 18.2% | 20.6% | 18.2% |
| `asr-v3-chain-prefetch` and shared CPU tail fusion | 15.7% | 22.0% | 20.2% |
| `asr-v3-stream`: 100 pairs, weights streamed every call | 7.4% | 32.0% | 33.7% |
| Registered DMA buffers | 19.8% | 40.0% | 39.0% |
| `asr-v3-adaptive`: adaptive depthwise schedule | 30.3% | 43.0% | 38.9% |

Values are the p50 latency reduction against the CPU baseline.

- **Chains:** 22 boundaries between pairs moved into the PL.
- **Stream:** 23 native operators cover 100 pairs and keep 77 boundaries
  inside the PL. All weights are uploaded on every inference, inside the
  timed call.
- **Registered DMA buffers:** the fixed parts of the program stay in kernel
  DMA memory, which cut ioctl time from about 29 ms to 21 ms on short inputs.
- **Adaptive depthwise schedule:** when the input has at most 16 frames, the
  64 depthwise MACs are spread across four channels instead of across time.

Adaptive result in milliseconds: CPU 55.9 / 95.1 / 149.9, FPGA
38.9 / 54.2 / 91.6.

## 5. 166.7 MHz timing closure, 13–14 October

The 1,024-MAC residual design was congested, with 199,929 overlapping nodes,
so it was dropped. 150 MHz was not reachable from the available PS clock
divider, so 166.667 MHz became the target. Each failed build removed its worst
path:

| Build | Change | Routed setup slack |
|---|---|---:|
| `pipe166` | Elastic register before requantization | −3.073 ns |
| `slice166` | Register before the pointwise input; legacy voice MAC removed | −0.536 ns |
| `outslice166` | Elastic output register | −0.075 ns |
| `drop166` | Depthwise quantizer pipeline split | −0.034 ns |
| `guard166` | Redundant header multiplier removed | 0.000 ns |
| `ab166` | DSP48E2 product register moved to the A/B input registers | **+0.043 ns** |

Speedup measured on `asr-v3-branch512-ab166`, as CPU → FPGA p50:

| Step | 0.5 s | 1 s | 2.5 s |
|---|---:|---:|---:|
| First qualified run | 56.5 → 30.2 ms (1.87x) | 96.4 → 41.6 ms (2.32x) | 149.5 → 70.3 ms (2.13x) |
| NEON output unpacking | 52.7 → 26.9 ms (1.96x) | 94.8 → 36.3 ms (2.61x) | 146.9 → 60.3 ms (2.43x) |
| Exact valid-frame frontend, final | 52.6 → 26.1 ms (2.01x) | 93.8 → 35.8 ms (2.62x) | 145.4 → 59.0 ms (2.47x) |

The final step removed unused frontend padding on both paths. The final audit
compared CPU and FPGA logits after every warm pair, 900 comparisons in total,
and all matched. See `reports/fused/FPGA_ASR_2X_COMPLETION_AUDIT.json`.

## 6. Larger Citrinet models, 15 October

Citrinet-512-LS and Citrinet-1024 (gamma 0.25) were run through the 100 MHz
bulk pointwise path. The retained-block engine supports 256 channels only.

| Model | Input | CPU p50 | FPGA p50 | CPU ÷ FPGA |
|---|---:|---:|---:|---:|
| 512 | 0.5 s | 153.3 ms | 222.8 ms | 0.69x |
| 512 | 2.5 s | 382.5 ms | 381.3 ms | 1.00x |
| 1024 | 0.5 s | 373.8 ms | 649.1 ms | 0.58x |
| 1024 | 2.5 s | 1039.6 ms | 975.1 ms | 1.07x |

Per-layer offload does not pay off for the wider models either. They would
need wider retained blocks.

## Accuracy

There is only a diagnostic check, not a representative corpus:
- **Diagnostic set:** nine recordings, made up of the user recording, three
  synthetic noise and level variants of it, and five LibriSpeech clips.
  - Through the 4-pair design, the FPGA and CPU paths made the same word
    errors: 24 of 269 words.
  - The 32-pair design and everything after it only accept 2.55 s of input.
    They were checked instead on 36 short slices of these recordings: FPGA
    logits, output lengths and text matched the CPU exactly.
- **Five-clip LibriSpeech set:** FP32 had 3 errors in 157 words and ORT INT8
  had 4.

## Tried and rejected

- **Sparse mel frontend:** same accuracy, but the frontend got slower.
- **Fixed graph shapes, frozen lengths:** no gain.
- **Prepacked weights on the bulk engine:** less host work, but no significant
  end-to-end gain.
- **Residual overlap and pipeline worker variants**
  (`software/ort_fpga_overlap*`, `software/ort_fpga_pipeline*`): no reliable
  gain.
- **Incremental Vivado implementation:** not covered by the installed license.
- **Reciprocal quantizer in the CPU tail:** bit-exact, but no faster.
