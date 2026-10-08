# Cached-layer board package

Board package for the V3 design: the `voice-cached` xmutil app, the cached
`qn_tile` driver and the QNC2 userspace client. It is installed over
`dma-deployment/` and reuses that folder's Python environment and model.
Depthwise convolutions use the native CPU kernel.

| Path | Contents |
|---|---|
| `voice-cached/` | Overlay source and `shell.json` |
| `tile-driver/` | Driver with the QNC2 LOAD/RUN ioctls; see [software/tile-driver/README.md](../software/tile-driver/README.md) |
| `software/` | `qn_cached.py`, `cached_smoke.py`, `test_cached.py` and updated runners |
| `source/` | Copy of the RTL and testbench this firmware was built from |
| `validation/` | Timing, utilization, DRC, simulation log and host parity results |

The protocol is specified in
[software/CACHED_LAYER_PROTOCOL.md](../software/CACHED_LAYER_PROTOCOL.md).

## Prepare

| File | How to make it |
|---|---|
| `voice-cached/voice-cached.bit.bin` | `bootgen -arch zynqmp -image scripts/voice_cached_dma.bif -process_bitstream bin -w on`, then copy `voice_cached_dma/voice_cached_dma.runs/impl_1/voice_cached_dma_top.bit.bin` |
| `voice-cached/voice-cached.dtbo` | `dtc -@ -I dts -O dtb -o voice-cached/voice-cached.dtbo voice-cached/voice-cached.dts` |
| `tile-driver/qn_tile_cached.ko` | `make` in `tile-driver/` on the board, then rename `qn_tile.ko` |
| `software/asr-baseline/native/libqn_depthwise.so` | gcc command in [dma-deployment/README.md](../dma-deployment/README.md) |

`scripts/voice_cached_dma.bif` holds an absolute path to the bitstream; edit
it for another checkout. The module's internal name stays `qn_tile`.

## Run

From `~/voice-deployment/dma-cached-update`, install the software over
`../dma-deployment/software/` and the firmware into
`/lib/firmware/xilinx/voice-cached/`. Then:

```bash
sudo rmmod qn_tile
sudo xmutil unloadapp
sudo xmutil loadapp voice-cached
echo 100000000 | sudo tee /sys/bus/platform/devices/voice-cached-clock/set_rate
sudo insmod tile-driver/qn_tile_cached.ko

cd ../dma-deployment
sudo .venv-dma/bin/python software/cached_smoke.py --device /dev/qn-tile --report cached-board.json
sudo .venv-dma/bin/python software/tile_smoke.py --device /dev/qn-tile
sudo .venv-dma/bin/python software/profile_dma.py --wav ../speech.wav --pointwise-backend cached --remove-dc --cpu-conv-backend native --cpu-conv-threads 4 --report hybrid-cached.json
```

- `cached_smoke.py` must report `all_exact: true` and
  `cross_fd_lease_checked: true`. It covers signed extremes, maximum
  dimensions, tails, layer replacement and a stale lease from another FD.
- The cached driver still accepts the legacy QNT1 tile ioctls. A legacy call
  invalidates the cached weights.
- On the 10 s clip expect 94 LOAD commands, 3,008 RUN packets and 699 ioctls.
  `--cached-batch-size 1` sends one RUN per ioctl for comparison.
- Errors are raised to the caller. Nothing silently falls back to the CPU.

Roll back to the tile design by unloading `qn_tile`, loading `voice-dma`
and inserting the batch driver. `--pointwise-backend tile` (the default)
runs the updated userspace against it.

Host tests, run from `software/`:

```sh
python3 test_cached.py
python3 cached_smoke.py --emulate
```
