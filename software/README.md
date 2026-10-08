# Software

Board software for Ubuntu 24.04 on the KV260 (Python 3.12). This folder holds
the latest version of every file; the `dma-*` package folders hold the copies
deployed at each stage.

| Path | Purpose |
|---|---|
| `kv260_voice.py` | UIO access to the V1 peripheral: dot-product chaining, grouped Conv1d reference, PCM24 capture, CTC collapse |
| `record_audio.py` | Records 10 s from the PL microphone FIFO |
| `qn_tile.py` | QNT1 tile client: packing, K chunking, batch ioctls |
| `qn_cached.py` | QNC2 cached-layer client: LOAD, batched RUN, result unpacking |
| `tile_smoke.py`, `batch_smoke.py`, `cached_smoke.py` | Physical arithmetic tests against INT64 references (`--emulate` for host runs where supported) |
| `profile_dma.py` | Full-model hybrid run with per-node timing; selects `--pointwise-backend` and `--cpu-conv-backend` |
| `test_cached.py` | Host tests for the QNC2 wire format, error handling and graph parity |
| `asr-baseline/` | QuartzNet CPU runner, hybrid runner, NeMo parity check and the native depthwise kernel |
| `tile-driver/` | `qn_tile` Linux driver; see [tile-driver/README.md](tile-driver/README.md) |
| `voice-uio.dtsi`, `voice-dma.dts`, `voice-cached.dts` | Device-tree sources for the three designs |
| `collect_board_profile.sh` | Read-only board inventory (device tree, drivers, xmutil state) |
| `CACHED_LAYER_PROTOCOL.md` | QNC2 packet format and ioctl ABI |

## ASR runners

`asr-baseline/model/` needs `model.onnx` from
`OpenVoiceOS/stt_en_quartznet15x5_onnx` at the revision in `revision.txt`.

```sh
python3 asr-baseline/quartznet_cpu.py speech.wav --threads 4 --remove-dc
python3 asr-baseline/quartznet_hybrid.py speech.wav --emulate-tile
python3 asr-baseline/validate_hybrid.py speech.wav --report hybrid-host.json
```

- `quartznet_cpu.py` is the CPU baseline. It uses `requirements.txt`.
- `quartznet_hybrid.py` runs the 94 pointwise convolutions in INT8 and the
  rest of the graph in FP32 NumPy. `--emulate-tile` (the default) does the
  INT8 matmul on the CPU, `--fp32-numpy` runs the whole graph in FP32 and
  `--device /dev/qn-tile` uses the FPGA. It needs `requirements-hybrid.txt`.
- `validate_hybrid.py` compares every Conv output against ONNX Runtime.
- `validate_original.py` compares the runner with the original NeMo
  JasperBlock code in `reference/`. It needs PyTorch and
  `reference/model_weights.ckpt` extracted from the NVIDIA `.nemo` archive.

Quantization is dynamic: activation scale is the layer's absolute maximum
/ 127, weight scale is per output channel, rounding is ties-to-even, and the
FP32 bias is added after dequantization.

## Native depthwise kernel

`asr-baseline/native/qn_depthwise.c` is an FP32 depthwise Conv1d for the
Cortex-A53 (NEON, 1–4 threads), called through `native_depthwise.py`.
`make` in `native/` builds a portable host version and `test_native.py` tests
it. The board build command is in
[dma-deployment/README.md](../dma-deployment/README.md). Host test results
are in `native/host/`.

## V1 peripheral

`python3 kv260_voice.py --selftest` runs on a host against a fake MMIO model.
On the board, `python3 kv260_voice.py --device /dev/uioN --audio 160` runs the
dot-product and capture smoke test.

- Dots longer than 4096 elements chain the INT32 accumulator into the next
  command's bias.
- `requantize` is an arithmetic right shift with saturation and optional
  ReLU, not a general scale multiply.
- The 1024-sample FIFO lasts only 64 ms, so long Python loops can drop audio.
