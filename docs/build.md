# Build, drivers and the Citrinet runtime

Tools: Vivado 2026.1 with part `xck26-sfvc784-2LV-c` and board
`xilinx.com:kv260_som:part0:2.0`. The tested board runs kernel
`6.8.0-1036-xilinx`. The Moonshine image build is in
[streaming.md](streaming.md).

## Citrinet FPGA image

```sh
vivado -mode batch -source scripts/project.tcl -tclargs check
vivado -mode batch -source scripts/project.tcl -tclargs build
```

The script creates `build/fpga/kv260_asr.xpr` from:
- `hardware/reference/asr_v2_system/asr_v2_system.bd`
- `hardware/reference/asr_v2_top.v`
- the branch512 RTL
- the constraints in `hardware/`

`check` checks block-design connectivity. `build` routes the design and writes
`build/fpga/kv260_asr.xsa`. The build requires setup slack of at least
0.001 ns, non-negative hold slack and no DRC errors. The script refuses to
overwrite `build/fpga`.

To make the app firmware:
1. Extract the `.bit` from the XSA.
2. Name it `asr-v3-branch512-ab166.bit` in `firmware/asr-v3-branch512-ab166/`.
3. In that folder, run:

```sh
bootgen -arch zynqmp -image boot.bif -process_bitstream bin -w on
dtc -@ -I dts -O dtb -o asr-v3-branch512-ab166.dtbo asr-v3-branch512-ab166.dts
```

The recorded build had +0.043 ns setup and +0.010 ns hold slack. A new route
can differ.

The `asr-v3-bulk` app (100 MHz bulk engine) has firmware sources in
`firmware/asr-v3-bulk/` and RTL in `rtl/experimental/qn_bulk_axis.v`. No
script here builds that image on its own. For Moonshine, `asr-v3-mic-select`
contains the same engine.

## RTL simulations

```sh
vivado -mode batch -source scripts/simulate.tcl -tclargs ab_mac_conformance
vivado -mode batch -source scripts/simulate.tcl -tclargs branch512_ab_fast_sim
vivado -mode batch -source scripts/simulate.tcl -tclargs branch512_ab_reset_sim
vivado -mode batch -source scripts/simulate.tcl -tclargs branch512_ab_payload_reset_sim
```

| Test | Covers |
|---|---|
| `ab_mac_conformance` | 203,980 cases against the vendor DSP primitive |
| `branch512_ab_fast_sim` | 25 residual branches, stalls and malformed packets |
| `branch512_ab_reset_sim`, `branch512_ab_payload_reset_sim` | Six pipeline and two output-buffer reset cases |

The full-block tests use the behavioral MAC model in `sim/fast/` for speed.

## Drivers

The two `qn_tile` drivers share a module name, so only one can be loaded at a
time:

| Driver | Used by |
|---|---|
| `drivers/bulk` | `asr-v3-bulk` and `asr-v3-mic-select` (Moonshine) |
| `drivers/branch` | `asr-v3-branch512-ab166` (Citrinet) |

Build them on the board against the running kernel's headers. Pass
`KDIR=/path/to/kernel/build` for another kernel tree.

```sh
test -f /lib/modules/$(uname -r)/build/Makefile
make -C drivers/bulk
make -C drivers/branch
modinfo -F vermagic drivers/bulk/qn_tile.ko
```

## Native libraries

On the ARM64 board:

```sh
sh scripts/build_native.sh            # Citrinet ORT operators and CPU kernels
sh scripts/build_moonshine.sh         # Moonshine bulk transport
sh scripts/build_moonshine_capture.sh # microphone FIFO reader
```

- **Output:** all three write to `build/native/`.
- **Headers:** `build_native.sh` needs the ONNX Runtime 1.30.0 C API headers in
  `software/ort_fpga_stream_branch512_neon/include/`.
- **Arithmetic:** `-ffp-contract=off` is part of the arithmetic contract, so
  do not add fast-math flags.

## Citrinet runtime

The Citrinet runtime works like this:
- `software/mvp/runtime.py` compiles the INT8 graph.
- The graph transforms in `software/latency/` and
  `software/ort_fpga_stream_branch512_neon/` replace the retained
  depthwise/pointwise blocks with FPGA custom operators.
- Squeeze-and-excitation, pooling and the residual tail stay on the CPU.
- One inference is 24 FPGA transactions. All weights are streamed inside the
  timed call.

The board scripts expect these files:
- `models/citrinet-256/cpu-int8-cse.onnx`, `frontend.npz` and `vocab.txt`;
- the built `.bit.bin` and `.dtbo` under `firmware/<app>/`;
- the modules under `drivers/prebuilt/$(uname -r)/bulk/` and `branch/`.

The model files only came from the dependency archive. They were derived from
`nvidia/stt_en_citrinet_256_ls` at revision
`c7cdacff0262bbb2a17771d20ec9f9f3b5cff6ed`. The scripts also check every file
against the hashes in `config/dependencies.json`.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
sudo .venv/bin/python scripts/setup_board.py --activate-bulk
sudo .venv/bin/python scripts/run_board.py -- clip.wav --runs 3 --verify-cpu --out reports/local/result.json
```

- **`setup_board.py`:** installs both apps under `/lib/firmware/xilinx`. It
  refuses to overwrite different files.
- **`run_board.py`:** loads the branch image, then restores the bulk image,
  driver, 100 MHz clock and DMA IRQ masks on exit.
- **Input:** a 16 kHz mono WAV with 320 to 40,959 samples.
- **`--verify-cpu`:** compares every output against the INT8 CPU graph.

## Board recovery

If a run is killed, first make sure nothing has `/dev/qn-tile` open. Then:

```sh
sudo rmmod qn_tile
sudo xmutil unloadapp
sudo xmutil loadapp k26-starter-kits   # or asr-v3-bulk for the Citrinet start state
```

Useful state for recovery:
- `reports/local/before-*.json` holds the DMA IRQ masks saved by `run_board.py`.
  IRQ numbers can change after an overlay reload, so match the two DMA IRQs.
- `/sys/module/qn_tile/parameters/bulk_protocol` is `1` when the bulk driver is
  loaded.
- `/sys/bus/platform/devices/<app>-clock/set_rate` shows the PL clock.
