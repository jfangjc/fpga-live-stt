# Integer oracle and CPU INT8 tools

These are the software tools behind the retained-block designs.

| File | Purpose |
|---|---|
| `oracle.py` | Exact integer convolution and a whole-graph interpreter that follows the ONNX shapes, masks and operator order |
| `experiment.py calibrate` | Collects activation ranges from calibration audio only |
| `experiment.py profile` | Profiles the CPU graph, ranks encoder blocks and extracts one block for separate timing |
| `experiment.py vectors` | Writes per-layer and per-block test vectors for the RTL testbenches |
| `experiment.py evaluate` | Runs the integer oracle over a manifest and reports WER |
| `build_cpu_int8.py` | Builds the ORT QLinearConv INT8 graph used as the CPU baseline |
| `benchmark_cpu.py` | Paired warm CPU benchmark |
| `transcribe_cpu_int8.py` | Resident CPU INT8 transcription of one or more WAV files |

The integer arithmetic:

| Stage | Rule |
|---|---|
| Activations | INT8, static per-tensor scale, nearest-even rounding with saturation |
| Weights | INT8 with a scale per output channel |
| Convolution | INT32 accumulation with an INT32 bias; overflow is checked |
| Requantization | Q31 multiplier and shift per channel, nearest-even rounding |
| Residual | Each branch is aligned with a Q16 multiplier, added, then shifted once |
| SE | Masked INT32 channel sums; the SE MLP and sigmoid run in FP32 on the CPU; the gates are returned as Q0.15 |

```sh
python -m unittest discover -s software/fused -v
python software/fused/experiment.py calibrate --manifest research/eval/librispeech-mini/calibration.jsonl --out reports/fused/calibration.json
python software/fused/build_cpu_int8.py --calibration-manifest research/eval/librispeech-mini/calibration.jsonl --evaluation-manifest research/eval/librispeech-mini/evaluation.jsonl --out research/fused/cpu-int8.onnx
```

Run these from the repository root.
