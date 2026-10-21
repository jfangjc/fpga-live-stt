# Board setup, Citrinet run and recovery

## Check the board

```sh
uname -m
uname -r
python3 --version
command -v xmutil modinfo insmod rmmod
cat /sys/class/fpga_manager/fpga0/state
```

The prebuilt modules need `aarch64` and kernel `6.8.0-1036-xilinx`. For any
other kernel, rebuild them ([drivers.md](drivers.md)). Do not force-load a
mismatched module.

## Install

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/setup_dependencies.py --archive /path/to/fpga-ai-accelerator-dependencies-1.0.0.zip
.venv/bin/python scripts/integrity.py
sudo .venv/bin/python scripts/setup_board.py --activate-bulk
```

- Setup installs the `asr-v3-bulk` and `asr-v3-branch512-ab166` apps under
  `/lib/firmware/xilinx`. It refuses to overwrite different apps with the same
  names.
- `--activate-bulk` loads the 100 MHz bulk image. This is the start state for
  Citrinet runs. Moonshine runs instead start from `k26-starter-kits`
  ([moonshine.md](moonshine.md)).

## Run Citrinet

```sh
sudo .venv/bin/python scripts/run_board.py -- /path/to/clip.wav \
  --runs 3 --verify-cpu --out reports/local/result.json
```

- Input: 16 kHz mono PCM16, PCM24 or PCM32 WAV, 320 to 40,959 samples
  (at most 256 feature frames). No resampling or truncation.
- The runner loads the branch image and driver, runs, then restores the bulk
  image, driver, 100 MHz clock and DMA IRQ masks, also after errors.
- `--verify-cpu` compares every warm output with the INT8 CPU graph and aborts
  on a mismatch.

How it runs: `software/mvp/runtime.py` builds one ONNX Runtime graph. The FPGA
executes retained depthwise and pointwise blocks as native custom operators
(24 transactions, 128 retained pairs per call, all weights uploaded inside the
timed call). The CPU runs squeeze-and-excitation, pooling, the residual tail
and the CTC WordPiece decode.

## Verify the bulk state

```sh
sudo xmutil listapps
cat /sys/module/qn_tile/parameters/bulk_protocol
cat /sys/bus/platform/devices/asr-v3-bulk-clock/set_rate
test -c /dev/qn-tile
```

Expect the bulk app active, protocol `1` and a clock of `99999999` (100 MHz
after divider rounding).

## Recover after an interrupted run

Make sure no process still holds `/dev/qn-tile`, then:

```sh
sudo rmmod qn_tile
sudo xmutil unloadapp
sudo xmutil loadapp asr-v3-bulk
printf '100000000\n' | sudo tee /sys/bus/platform/devices/asr-v3-bulk-clock/set_rate
sudo insmod drivers/prebuilt/$(uname -r)/bulk/qn_tile.ko
```

To return to the Moonshine start state, unload `qn_tile` and load
`k26-starter-kits` instead. If DMA IRQ masks were not restored, use the
`before-*.json` file the runner saved under `reports/local/`. Match the two
DMA IRQs; their numbers can change after an overlay reload.

## Common failures

| Error | Action |
|---|---|
| Asset missing or changed | Rerun `scripts/setup_dependencies.py` with the pinned archive, then `scripts/integrity.py`. |
| No prebuilt module for this kernel | Build both drivers for the running kernel. |
| Existing FPGA app differs | Rename the existing app, then install. |
| Wrong protocol or module version | Activate the bulk app with the supplied bulk module. |
| Expected two PL DMA IRQs | Check overlay loading and the kernel log for AXI DMA errors. |
| Output or evidence path exists | Choose a new path. |
