# KV260 speech-to-text latency measurements

Board: `ubuntu@192.168.1.111`, ZynqMP KV260 revB, four Cortex-A53 cores, 3.8 GiB RAM, no swap. Ubuntu 24.04.5 LTS, kernel 6.8.0-1036-xilinx. Measurements were collected on 27 October 2026.

The models ran one at a time, in the requested order, using the supplied `bench.py` method. Each model used a separate process, two untimed warmup clips, and the same 40 LibriSpeech test-clean clips (307.170 seconds total, 2.145–18.545 seconds per clip, seed 0). There was a cooldown of at least 30 seconds between models. No inference models ran concurrently. Download and file transfer activity finished before the relevant timed stage.

**Latency means time from the complete clip being available in memory to the final transcript.** It includes preprocessing and decoding. It excludes model loading, audio file I/O, warmups and downloads. These are CPU measurements; the FPGA/DPU was not used.

| Model | Clips | p50 (s) | p90 (s) | Max (s) | RTF | WER | Peak RSS (MiB) | Load (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| QuartzNet15x5 | 40 | 1.334 | 2.709 | 3.579 | 0.198 | 5.43% | 200 | 2.16 |
| Citrinet-256-LS | 40 | 0.414 | 0.835 | 1.041 | 0.063 | 5.55% | 165 | 3.43 |
| Citrinet-512-LS | 40 | 1.331 | 2.632 | 3.133 | 0.188 | 5.78% | 278 | 4.02 |
| Citrinet-1024-gamma-0.25 | 40 | 3.941 | 8.804 | 11.527 | 0.607 | 3.24% | 708 | 6.61 |
| Whisper Base | 40 | 8.498 | 10.555 | 11.936 | 1.125 | 7.40% | 371 | 6.75 |
| Whisper Small | 40 | 27.171 | 30.848 | 35.778 | 3.582 | 4.97% | 684 | 8.00 |
| Whisper Large-V3-Turbo | 40 | 119.074 | 122.460 | 125.553 | 15.521 | 3.12% | 1675 | 58.44 |
| Moonshine Tiny | 40 | 1.650 | 2.944 | 4.434 | 0.244 | 4.62% | 430 | 10.69 |
| Moonshine Streaming Tiny | 40 | 6.722 | 12.244 | 18.080 | 0.998 | 8.32% | 313 | 1.70 |
| Moonshine Streaming Small | 40 | 15.859 | 27.191 | 38.087 | 2.140 | 5.55% | 563 | 1.80 |

RTF is total processing time divided by total audio duration; below 1 is faster than real time. Percentiles describe this fixed set of variable-length clips. WER is a sanity check on this small sample, not a full-dataset accuracy estimate. Peak RSS includes model initialization and warmups.
The LS WordPiece decoder retains punctuation spacing, matching the installed NeMo tokenizer’s `clean_up_tokenization_spaces=False` setting. The supplied WER normalizer counts spaced apostrophes in contractions as errors; the saved transcripts expose these formatting differences.

## Runtime settings

- NVIDIA models: ONNX Runtime CPU, float32, greedy CTC, NumPy feature extraction, four intra-op threads.
- Whisper: multilingual Base, multilingual Small, and Large-V3-Turbo via faster-whisper/CTranslate2, CPU int8, four threads, language English, beam size 1, no timestamps, VAD off, previous-text conditioning off.
- Moonshine Tiny: original ONNX Runtime adapter and float32 weights (the original constructor defaults to float32), greedy decoding, four intra-op threads and one inter-op thread.
- Moonshine Streaming Tiny/Small: vendor `moonshine-voice` quantized ORT models, `Transcriber.transcribe_without_streaming()` with default vendor decoding/VAD settings. Native ONNX Runtime chooses its thread pools automatically on the four-core board. These rows measure offline full-clip-to-final processing, not streaming first-token latency or live endpointing delay.

The board kernel did not expose `/sys/devices/system/cpu/cpufreq/policy0/scaling_governor` or any thermal-zone temperature files. The documented performance-governor command could not be applied, and temperature/throttling could not be checked. Temperature fields are therefore unavailable (`NaN` in the raw outputs).

## Changes required to run the supplied method

- Added the requested checkpoints, including the exact `-LS` Citrinet variants and Whisper Large-V3-Turbo.
- Downloaded the official QuartzNet checkpoint directly because the installed NeMo registry no longer listed its legacy identifier.
- Matched NeMo feature normalization to valid frames, masked/padded the feature tail, and checked it numerically against each checkpoint’s own preprocessor.
- Supported QuartzNet exports with no length input and cropped padded CTC output frames.
- Decoded the LS checkpoints as WordPiece; retained SentencePiece decoding for the gamma checkpoint and character decoding for QuartzNet.
- Set Moonshine Tiny’s ONNX thread counts explicitly; added the vendor adapter for the streaming checkpoints.
- Added progress records in RAM, durable output copies after each model, and sequential status logs. Final metrics still use the supplied per-clip timing and aggregation calculations.

## Export validation

| Model | Maximum absolute feature error vs NeMo |
|---|---:|
| QuartzNet15x5 | 0.00005722 |
| Citrinet-256-LS | 0.00007772 |
| Citrinet-512-LS | 0.00007772 |
| Citrinet-1024-gamma-0.25 | 0.00007772 |

Validation used a deterministic 160,123-sample float32 waveform; all errors were below 0.0001. The exported graphs were also exercised with the variable-length speech clips. QuartzNet’s measured WER can be checked against the original README’s 4–6% sanity range.

## Reproducibility

Manifest SHA-256: `fcfc1bf254296ab0067563e13b873c2dd3b01204bb134172b0d84c00d681e800`.

The `data/` directory contains the exact WAVs and manifest. `results/` contains per-clip transcripts/timings, per-model summaries, logs, `status.json`, and `summary.csv`. `environment.json` records board and package details; `weights.json` records the cached weight paths and Hugging Face revision hashes. `model-files.json` records checksums of the NVIDIA exports and tokenizer configurations.

The first three models were measured in one sequential stage. After that stage ended, the final export was transferred. The first Citrinet-1024 warmup attempt failed because its short export example froze a mask cache at 512 frames. No latency was recorded from that attempt; its log is preserved in `results/attempts/`. The export was corrected by explicitly initializing a long mask cache and checked on the shortest and longest test clips. The remaining seven models then ran sequentially with another initial cooldown. There were no transfers during timed inference.

Installed runtime versions:
- `numpy==2.5.4`
- `soundfile==0.14.0`
- `jiwer==4.0.0`
- `onnxruntime==1.31.1`
- `faster-whisper==1.2.1`
- `ctranslate2==4.8.4`
- `moonshine-voice==0.1.5`
- `useful-moonshine-onnx==20251121`

Checkpoint sources:

- [NVIDIA QuartzNet](https://api.ngc.nvidia.com/v2/models/nvidia/nemo/stt_en_quartznet15x5/versions/1.0.0rc1/files/stt_en_quartznet15x5.nemo)
- [NVIDIA Citrinet-256-LS](https://huggingface.co/nvidia/stt_en_citrinet_256_ls)
- [NVIDIA Citrinet-512-LS](https://huggingface.co/nvidia/stt_en_citrinet_512_ls)
- [NVIDIA Citrinet-1024 gamma 0.25](https://huggingface.co/nvidia/stt_en_citrinet_1024_gamma_0_25)
- [Systran faster-whisper models](https://github.com/SYSTRAN/faster-whisper)
- [Moonshine](https://github.com/moonshine-ai/moonshine)
