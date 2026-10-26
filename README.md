# KV260 speech-to-text benchmark

Adapted from the supplied preliminary benchmark to test these ten models on the KV260's Cortex-A53 CPU, one model at a time:

1. QuartzNet15x5
2. Citrinet-256-LS
3. Citrinet-512-LS
4. Citrinet-1024-gamma-0.25
5. Whisper Base
6. Whisper Small
7. Whisper Large-V3-Turbo
8. Moonshine Tiny
9. Moonshine Streaming Tiny
10. Moonshine Streaming Small

See [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md) for results and qualifications and [RUNNING.md](RUNNING.md) for reproduction instructions. The original preliminary README is retained as [README-original.md](README-original.md).

The method uses 40 fixed LibriSpeech test-clean clips, two untimed warmups, isolated model processes, and a cooldown of at least 30 seconds between models. Latency is full-clip-to-final transcript processing time; streaming checkpoints use the same offline timing boundary. The FPGA/DPU is not used.

`results/summary.csv` contains model-level measurements; per-model CSV files contain all clip timings and transcripts. Environment, weight revisions, model checksums and export validation records are saved alongside the code.
