# Results history

All numbers are KV260 measurements on the same 10 s English recording unless
stated otherwise. Timings are whole-file: frontend, model and greedy CTC
decode. They exclude model loading and file reading, so they are not live
latency. From stage 3 on, the recording has its DC offset removed
(`--remove-dc`; the raw file has a DC mean of about -0.096 full scale).

There is no reference transcript, so no WER was measured. "Same transcript"
means the hybrid matched the CPU output on this one clip.

## 1. Microphone and AXI-Lite dot product, 8 October

The V1 design (`Prototype.xpr`) adds two blocks behind one 64 KiB AXI-Lite
peripheral at 0xA0000000:
- an SPH0645 I2S receiver with a 1024-sample FIFO (64 ms at 16 kHz);
- a signed INT8 dot product with 32 DSP48E2 multipliers, 32 elements every
  two clocks (about 1.6 GMAC/s ideal).

| Item | Value |
|---|---|
| Routed timing at 100 MHz | setup +0.353 ns, hold +0.028 ns |
| Resources | 2,261 LUTs, 1,095 registers, 32 DSPs, 16 RAMB18 |
| XSIM | 46 dot-product cases, 8 microphone vectors, AXI/FIFO tests pass |
| Board dot product | -32384, as expected |
| Board capture, 10 s | 160,000 samples, 0 new drops |

- **Clock:** the first overlay asked for 99,999,001 Hz and the board rounded
  it to 93.75 MHz, which puts BCLK below the microphone minimum. Requesting
  100,000,000 Hz reads back 99,999,999 Hz.
- **Not usable for inference:** one MMIO command per output and Python
  operand copies make a full model far too slow on this path.

## 2. CPU baseline, 8 October

QuartzNet15x5 ONNX export in ONNX Runtime, 4 Cortex-A53 threads.

| Run | Total | RTF |
|---|---:|---:|
| Raw audio, before frame-trim fix | 2.030 s | 0.203 |
| DC removed, before frame-trim fix | 1.985 s | 0.198 |
| DC removed, after frame-trim fix | 1.958 s | 0.196 |
| Same, repeated with the cached stage | 1.965 s | 0.197 |

The frame-trim fix drops the extra end STFT frame so the network sees exactly
ceil(samples/160) frames. With it, the runner matches the original NeMo model
frame for frame on four test lengths.

## 3. DMA tile engine (V2), 8 October

`rtl/qn_tile_axis.v` computes a 16 time x 16 output channel INT8 tile with
256 DSP48E2s. Each QNT1 packet carries K rows of inputs and K rows of weights
and returns 256 INT32 values. An AXI DMA moves packets between DDR and the
tile, and the `qn_tile` driver exposes it as `/dev/qn-tile`. The 94 pointwise
convolutions go through the tile; everything else stays on the CPU.

| Item | Value |
|---|---|
| Standalone tile, routed | setup +2.431 ns; 256 DSPs, 8 BRAM tiles, 2,345 LUTs |
| Tile XSIM | 13 arithmetic and protocol cases pass |
| Integrated design, routed | setup +0.198 ns, hold +0.010 ns; 11,401 LUTs, 288 DSPs, 21 BRAM tiles |
| Board tile round trip | K=1 0.82 ms, K=17 0.57 ms, K=257 0.35 ms, K=1024 0.36 ms |
| Host FP32 NumPy graph vs ONNX Runtime | all 171 Conv outputs match; 100% frame agreement, max log-prob error 5.2e-5 |
| Host INT8 vs FP32 | 97.6% frame agreement, one word changed |

- **First board test timed out:** the generated AXI DMA had its optional
  status stream enabled, and nothing drove it, so receive completion never
  arrived. Disabling `c_sg_include_stscntrl_strm` fixed it (`dma-status-fix/`).
  The corrected tile passed K=1/17/257/1024, tails and K chunking against
  INT64 arithmetic.
- **Full model:** 27.71 s (RTF 2.771) with 77,376 synchronous tile calls,
  same transcript. The CPU baseline was 1.958 s.

## 4. Batched ioctls, 8 October

`dma-batch-update/` queues up to 128 tile packets per ioctl (each keeps its
own TLAST) and waits once. The FPGA is unchanged. The driver uses about
4.33 MB of coherent DMA buffers.

| Batch size | Total | Ioctls | Pointwise nodes | Inside ioctls | Other graph |
|---:|---:|---:|---:|---:|---:|
| 64 | 13.41 s | 1,209 | 10.96 s | — | 2.36 s |
| 128 | 12.83 s | 605 | 10.39 s | 2.66 s | 2.36 s |

DMA input traffic was 1,094,902,784 bytes per run. 7.73 s of pointwise time
was spent outside ioctls, in quantization, packing, copies and result
assembly.

## 5. Contiguous packing, 8 October

`dma-packing-update/` reorders activation and weight tiles into contiguous
memory once per K chunk and passes the buffers straight to the ioctl.
Packet bytes are unchanged; all 266 graph outputs are bit-exact in host
emulation.

| Total | RTF | Pointwise | Inside ioctls | Other graph |
|---:|---:|---:|---:|---:|
| 8.35 s | 0.835 | 5.90 s | 2.72 s | 2.36 s |

First run faster than the clip duration, still 4.3x slower than CPU.

## 6. Packet buffer reuse, 8 October

`dma-reuse-update/` allocates one packet buffer per K chunk and rewrites the
weight rows only when the output-channel offset changes. 266 nodes stay
bit-exact and 25 extra INT64 checks pass. Host packing was 35–40% faster on
the two largest layers.

| Total | RTF | Pointwise | Inside ioctls | Other graph | Peak RSS |
|---:|---:|---:|---:|---:|---:|
| 7.88 s | 0.788 | 5.43 s | 2.74 s | 2.36 s | 281 MiB |

A CPU-only profile of this run put 2.175 s in the 77 depthwise Conv nodes,
0.159 s in Relu and 0.023 s in Add.

## 7. Native NEON depthwise convolution, 8 October

`dma-native-conv-update/` adds `qn_depthwise.c`, a Cortex-A53 NEON FP32
depthwise kernel (16 outputs per vector loop, 1–4 threads), selected with
`--cpu-conv-backend native`. The 94 FPGA nodes are unchanged.

| CPU threads | Total | RTF | Pointwise | Inside ioctls | Other graph |
|---:|---:|---:|---:|---:|---:|
| 4 | 6.303 s | 0.630 | 5.42 s | 2.71 s | 0.789 s |
| 1 | 7.669 s | 0.767 | 5.42 s | 2.72 s | 2.16 s |

- **Host checks:** 462 model-derived comparisons pass (max scaled error
  2.4e-7). The full graph is not bit-exact with NumPy: frame agreement was
  100%, 92.86% and 96.4% at 100, 251 and 1000 frames. The board transcripts matched the previous runs.
- **Pointwise now dominates:** 86% of the 6.30 s. Moving data was the next
  problem: every 16x16 output tile resent both its inputs and its weights.

## 8. Cached-layer engine (V3), 9 October

`rtl/qn_cached_axis.v` loads a layer's weights once (QNC2 LOAD, up to 1 MiB in
32 UltraRAMs) and then runs 16 time positions across all output channels per
RUN packet. The driver batches up to 128 RUN packets per ioctl. Quantization
and arithmetic are unchanged.

| Item | Value |
|---|---|
| Routed timing at 100 MHz | setup +0.192 ns, hold +0.010 ns |
| Resources | 11,881 LUTs, 14,288 registers, 17 BRAM tiles, 32 URAM, 288 DSPs |
| XSIM | 69 arithmetic, protocol and reset cases pass |
| Host emulation | all 266 graph nodes match the tile path |

Board results:

| Configuration | Total | RTF |
|---|---:|---:|
| CPU only, 4 threads | 1.965 s | 0.197 |
| Tile hybrid, native depthwise (stage 7) | 6.303 s | 0.630 |
| Cached hybrid, native depthwise | 3.499 s | 0.350 |

| Metric | Tile hybrid | Cached hybrid |
|---|---:|---:|
| DMA input bytes | 1,094,902,784 | 36,831,712 |
| DMA output bytes | — | 79,282,656 |
| Ioctls | 605 | 699 |
| DMA commands | 77,376 tiles | 94 LOAD + 3,008 RUN |
| Pointwise time | 5.42 s | 2.61 s |
| Inside ioctls | 2.71 s | 1.09 s |
| Other graph | 0.789 s | 0.795 s |

- **44.5% faster than the tile hybrid, still 1.78x slower than CPU.**
- **Traffic matched the estimate:** 29.7x less input data (17,088,512 bytes
  of weights plus 19,693,568 of activations, plus headers). Weights are
  still reloaded once per layer per inference; the largest layer is
  524,288 bytes.
- **Host work is now the limit:** 1.52 s of pointwise time is outside the
  ioctls (quantization, packing, unpacking, FP32 rescale and bias). Removing
  every ioctl would leave about 2.41 s, above the CPU baseline.
- Other graph time: Conv 0.612 s, Relu 0.158 s, Add 0.024 s.

## What was learned

- The CPU baseline is strong. QuartzNet15x5 runs a 10 s clip in under 2 s on
  four A53 cores, so the accelerator must remove almost all host overhead.
- Each stage moved the bottleneck: per-tile ioctls, then Python packing, then
  CPU depthwise convolution, then DMA traffic, then host quantization and
  result handling.
- An accelerator that only does the matrix multiply cannot win here. The
  next design needs requantization, bias and activation in the PL and whole
  blocks kept on the FPGA, with a native host runtime instead of Python.
- This led to prototype v2: a smaller model (Citrinet-256), native ONNX
  Runtime custom operators and retained depthwise/pointwise pairs.

## Tried and rejected

- **ONNX Runtime for the CPU depthwise convolutions** (`dma-cpu-conv-update/`):
  8.56 s against 8.35 s with NumPy, and 2.10 s of extra session setup.
  Per-node error was small (3.6e-7 relative, 231 checks), but the full graph
  was not bit-exact (97.2% frame agreement on the host).
- **One thread for the native depthwise kernel:** 7.67 s against 6.30 s with
  four.
- **AMD DPU:** an operator screen of the graph found all 77 depthwise layers
  exceed the DPU's direct padding limit and 16 exceed its B4096 bank depth.
  Its supported toolchain is also older than the board's kernel.
- **External accelerators:** the ASUS UGen300 (Hailo-10H) is a 10 Gb/s
  USB-C device, and nothing confirmed it works on the KV260's 5 Gb/s USB 3.0
  ports. It would also replace QuartzNet with the vendor's Whisper and move
  recognition off the FPGA. The Coral USB Edge TPU needs
  fixed-shape TFLite models and leaves unsupported operators on the CPU.
  Neither was bought or tested.
