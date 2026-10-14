# Model research

## Why Citrinet-256

`nvidia/stt_en_citrinet_256_ls` was picked to fit a convolution accelerator.
Its published WER is 3.8% on LibriSpeech test-clean and 9.8% on test-other.

- **Pointwise work:** pointwise convolutions are 94% of its MACs, 2.57 G of the
  2.73 G for 10 s of audio.
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

## Files

| Path | Contents |
|---|---|
| `citrinet_inspection.json` | Config, tensor hashes and graph census of the exact checkpoint |
| `*_nemo_v1.23.0.py` | Pinned upstream NeMo sources used for export and parity |
| `export/<model>/` | Exported ONNX metadata and validation reports per model |
| `eval/` | Manifests for the LibriSpeech calibration and evaluation clips, the user recording and its quiet and noise variants; the audio is not committed |
| `fused/` | Build reports for the CPU INT8 and QDQ graphs |

## Larger models

- **`citrinet-512-ls`:** the INT8 candidate is `cpu-int8-safe.onnx`, which has a
  0.01 minimum quantization range. The first INT8 export failed the INT32
  accumulator-bound audit.
- **`citrinet-1024-gamma-0.25`:** used because NVIDIA's 1024-LS repository had
  no weights. It decodes with its own SentencePiece `tokenizer.model`, not the
  vocabulary stored in the archive.

Both models are 512 or 1024 channels wide, but the retained-block engine only
supports 256. They were therefore run through the bulk pointwise engine; see
[RESULTS.md](../RESULTS.md) section 6.
