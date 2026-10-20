# Model research

## Why Citrinet-256

`nvidia/stt_en_citrinet_256_ls` (9,767,441 parameters) was picked to fit a
convolution accelerator. Its published WER is 3.8% on LibriSpeech test-clean
and 9.8% on test-other.

- **Pointwise work:** pointwise convolutions are 94% of its MACs: 2,572,303,104
  of 2,732,405,760 for 1,008 frames (about 10 s of audio).
- **Operators:** everything else is depthwise convolution, masks, ReLU,
  residuals and 23 global squeeze-and-excitation (SE) blocks. There is no
  attention.
- **Downsampling:** stride two after blocks 1, 7 and 14, so the output has
  `ceil(frames/8)` frames.

The global SE blocks and symmetric kernels mean the model is not causal. Live
use has to process buffered windows.

Alternatives considered:
- **QuartzNet:** the earlier prototype's model. Its hybrid was 1.78x slower than
  its own CPU baseline.
- **Conformer-CTC small and streaming Zipformer:** need attention and
  transducer support, which the accelerator does not have.

## Whisper

Whisper (base, small, large-v3-turbo) was the next step once live captions
became the goal; see [software/whisper/README.md](../software/whisper/README.md).
All three were too slow for live use because the encoder always processes a
30 s window.

Candidates noted for a live system, none benchmarked here:
- **Moonshine Streaming Tiny, then Small:** sliding-window encoder that keeps
  finished states, so audio is encoded incrementally. English only.
- **Streaming Zipformer (sherpa-onnx, about 20M parameters)** and **Parakeet
  Realtime EOU 120M:** cache-aware streaming transducers with more convolution
  work that could reuse the MAC engines.

## Files

| Path | Contents |
|---|---|
| `citrinet_inspection.json`, `citrinet_hf_metadata.json` | Config, tensor hashes and graph census of the exact checkpoint |
| `*_nemo_v1.23.0.py` | Pinned upstream NeMo sources used for export and parity |
| `export/citrinet-256-ls/` | Export validation report and vocabulary |
| `fused/` | Build reports for the CPU INT8, simplified and QDQ graphs, plus block test vectors |
| `eval/` | Manifests for the LibriSpeech calibration and evaluation clips, the user recording and its quiet and noise variants |
| `whisper-latency/`, `whisper-validation/` | Manifests for the three Whisper timing clips and the ten-speaker LibriSpeech test-clean accuracy sample |
| `citrinet_host_cpu.json`, `cpu-environment-lock.txt` | Host CPU baseline and its package lock |
| `librispeech_test_rows.json` | Source rows for the LibriSpeech selections |

The audio itself is not committed. LibriSpeech is CC BY 4.0
([OpenSLR 12](https://www.openslr.org/12/)).
