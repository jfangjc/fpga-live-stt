# DMA tile board package

Base board package for the V2 design: the `voice-dma` xmutil app, the
`qn_tile` driver (`/dev/qn-tile`), and the CPU and hybrid QuartzNet runners.
The later `dma-*-update/` folders are applied on top of this one.

On the board this folder lived at `~/voice-deployment/dma-deployment`, with
the test recording at `~/voice-deployment/speech.wav`. The driver only loads
on kernel `6.8.0-1015-xilinx`.

## Prepare

These files are build outputs and must be added before copying:

| File | How to make it |
|---|---|
| `voice-dma/voice-dma.bit.bin` | `bootgen -arch zynqmp -image scripts/voice_dma_bitstream.bif -process_bitstream bin -w on` from the repo root, then copy `voice_dma/voice_dma.runs/impl_1/voice_dma_top.bit.bin` |
| `voice-dma/voice-dma.dtbo` | `dtc -@ -I dts -O dtb -o voice-dma/voice-dma.dtbo voice-dma/voice-dma.dts` |
| `tile-driver/qn_tile.ko` | `make` in `tile-driver/` on the board, against its kernel headers |
| `software/asr-baseline/model/model.onnx` | ONNX file from `OpenVoiceOS/stt_en_quartznet15x5_onnx`, revision in `model/revision.txt` |

## Run

```bash
cd ~/voice-deployment/dma-deployment
python3 -m venv .venv-dma
.venv-dma/bin/python -m pip install -r software/asr-baseline/requirements-hybrid.txt

sudo mkdir -p /lib/firmware/xilinx/voice-dma
sudo install -m 0644 voice-dma/voice-dma.bit.bin voice-dma/voice-dma.dtbo voice-dma/shell.json /lib/firmware/xilinx/voice-dma/
sudo xmutil unloadapp
sudo xmutil loadapp voice-dma
echo 100000000 | sudo tee /sys/bus/platform/devices/voice-dma-clock/set_rate
sudo insmod tile-driver/qn_tile.ko

sudo .venv-dma/bin/python software/tile_smoke.py --device /dev/qn-tile
.venv-dma/bin/python software/asr-baseline/quartznet_cpu.py ../speech.wav --threads 4 --remove-dc
sudo .venv-dma/bin/python software/asr-baseline/quartznet_hybrid.py ../speech.wav --device /dev/qn-tile --remove-dc --report hybrid-dma.json
```

- `tile_smoke.py` must report `PASS` before running the model. It checks
  K=1/17/257/1024, tails and K chunking against INT64 arithmetic.
- The DMA engine is built into the kernel; no `modprobe xilinx_dma` is needed.
- A failed transfer takes up to 10 s to time out. If DMA termination fails,
  the module stays pinned until reboot. Do not force-remove it.
- The microphone UIO is still named `voice-prototype`. Find its index with
  `grep -H '^voice-prototype$' /sys/class/uio/uio*/name`;
  `software/record_audio.py --device /dev/uioN --output <wav>` records 10 s.

Restore the V1 design:

```bash
sudo rmmod qn_tile
sudo xmutil unloadapp
sudo xmutil loadapp voice-prototype
echo 100000000 | sudo tee /sys/bus/platform/devices/voice-pl0-clock/set_rate
```

## Updates

Each update folder holds only the changed files. Copy it next to this folder,
then install its files over the same paths here.

| Folder | Changes | Run with |
|---|---|---|
| `dma-status-fix/` | Firmware only: rebuilt `voice-dma` with the DMA status stream disabled | `tile_smoke.py` |
| `dma-batch-update/` | Batch ioctl driver (`tile-driver/`; deployed as `qn_tile_batch.ko`), `qn_tile.py`, `batch_smoke.py`, `quartznet_hybrid.py` | `batch_smoke.py --device /dev/qn-tile --report batch-board.json`, then `quartznet_hybrid.py ... --dma-batch-size 64` |
| `dma-packing-update/` | `qn_tile.py`, `profile_dma.py` | `profile_dma.py --wav ../speech.wav --batch-size 128 --remove-dc --report hybrid-packing128.json` |
| `dma-cpu-conv-update/` | `quartznet_hybrid.py`, `profile_dma.py` with `--cpu-conv-backend ort` | add `--cpu-conv-backend ort` |
| `dma-reuse-update/` | `qn_tile.py` | as for packing, with `--cpu-conv-backend numpy` |
| `dma-native-conv-update/` | `native_depthwise.py`, `native_smoke.py`, `native/qn_depthwise.c`, updated runners | add `--cpu-conv-backend native --cpu-conv-threads 4` |

Build the native depthwise library on the board:

```bash
gcc -O3 -std=c11 -mcpu=cortex-a53 -Wall -Wextra -Werror -fno-fast-math -ffp-contract=off -fPIC -shared -pthread ../dma-native-conv-update/software/asr-baseline/native/qn_depthwise.c -o software/asr-baseline/native/libqn_depthwise.so
.venv-dma/bin/python software/asr-baseline/native_smoke.py --library software/asr-baseline/native/libqn_depthwise.so --report native-smoke.json
```

Keep `-fno-fast-math` and `-ffp-contract=off`; fused or reordered arithmetic
changes the outputs. Each folder's `validation/` holds that stage's results.
