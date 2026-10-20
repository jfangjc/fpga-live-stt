# Deployment

The KV260 runs Ubuntu 24.04 with a Xilinx 6.8 kernel. Each design is loaded as
an `xmutil` application. The FPGA is driven through the Linux AXI DMAengine
and a small `qn_tile` character driver (`/dev/qn-tile`). XRT and the DPU are
not used.

| Directory | Contents |
|---|---|
| `asr-v2/`, `asr-v2.dts` | Base image: QNC2 cached engine and microphone |
| `asr-v3-<design>/` | Firmware app for each design: device tree, `shell.json`, `boot.bif` and, for most designs, `activate.sh` |
| `driver/` | Base `qn_tile` driver for the QNC2 protocol |
| `experimental-<design>/` | `qn_tile` driver for each later protocol, with its packet-validation tests |
| `experimental-stream-branch/` | Driver for `asr-v3-branch512-ab166`, used by the MVP |

The bitstreams (`*.bit`, `*.bit.bin`), XSAs and compiled `.ko` files are build
outputs and are not committed. Producing them for a design:

1. `scripts/prepare_<design>_firmware.py` checks the routed timing, DRC and
   simulation evidence.
2. Convert the bitstream from inside the design's directory:

   ```sh
   bootgen -arch zynqmp -image boot.bif -process_bitstream bin -w on
   ```

3. Compile the overlay:

   ```sh
   dtc -@ -I dts -O dtb -o <design>.dtbo <design>.dts
   ```

4. Build the driver with `make` in `experimental-<design>/`, against the board's
   kernel headers. The MVP and Whisper runners also expect the bulk driver
   copied to `kernel-compat/<kernel>/bulk/qn_tile.ko`.

## Install an application

```sh
sudo mkdir -p /lib/firmware/xilinx/asr-v3-bulk
sudo install -m 0644 asr-v3-bulk/asr-v3-bulk.bit.bin asr-v3-bulk/asr-v3-bulk.dtbo asr-v3-bulk/shell.json /lib/firmware/xilinx/asr-v3-bulk/
sudo sh asr-v3-bulk/activate.sh
```

`activate.sh` first unloads the current driver, so close every `/dev/qn-tile`
client before running it. It then:
- loads the application and sets the PL clock;
- inserts the matching driver;
- checks the driver's protocol parameters.

If any step fails, it restores the previous application and driver.

The `scripts/run_*_board.sh` runners, including `run_mvp_board.sh`, do the same
around a single job. Afterwards they always restore `asr-v3-bulk` at 100 MHz.
The Whisper runners start from `k26-starter-kits` instead and return to it; see
[software/whisper/README.md](../software/whisper/README.md).

## Python environment

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r software/requirements-runtime.txt
```

## Manual rollback to the base image

This needs the base driver built with `make` in `driver/`.

```sh
sudo rmmod qn_tile
sudo xmutil unloadapp
sudo xmutil loadapp asr-v2
echo 100000000 | sudo tee /sys/bus/platform/devices/asr-v2-clock/set_rate
sudo insmod driver/qn_tile.ko
```

Board safety: only access the 0xA00x_xxxx addresses while an overlay is loaded
and its clocks are running. An unanswered AXI read freezes the board until it
is power-cycled.
