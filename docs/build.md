# Build from source

Running the snapshot does not need FPGA tools. This page is for changes to the
RTL, native libraries or drivers. Install the dependency archive first
([dependencies.md](dependencies.md)): it provides the generated block design,
ONNX Runtime headers, model, firmware and driver sources.

## FPGA project

Vivado 2026.1, part `xck26-sfvc784-2LV-c`, board
`xilinx.com:kv260_som:part0:2.0`. From the repository root:

```sh
vivado -mode batch -source scripts/project.tcl -tclargs check
vivado -mode batch -source scripts/project.tcl -tclargs build
```

- `check` imports the reference block design, adds the RTL and constraints,
  regenerates IP and checks connectivity. It creates `build/fpga/kv260_asr.xpr`.
- `build` synthesizes and routes. It needs setup slack of at least 0.001 ns,
  nonnegative hold slack and no DRC errors or critical warnings, then writes an
  XSA under `build/fpga`.
- Both refuse to overwrite an existing `build/fpga`.
- The script rebuilds the `asr-v3-branch512-ab166` inference image, not the
  bulk image. The shipped image closed at +0.043 ns setup, +0.010 ns hold.
- Microphone capture is not qualified at 166.667 MHz.

A rebuilt bitstream needs a matching overlay and a new board test before it
replaces the supplied firmware.

## RTL simulations

```sh
vivado -mode batch -source scripts/simulate.tcl -tclargs ab_mac_conformance
vivado -mode batch -source scripts/simulate.tcl -tclargs branch512_ab_fast_sim
vivado -mode batch -source scripts/simulate.tcl -tclargs branch512_ab_reset_sim
vivado -mode batch -source scripts/simulate.tcl -tclargs branch512_ab_payload_reset_sim
```

| Test | Checks |
|---|---|
| `ab_mac_conformance` | Behavioral MAC model against the vendor DSP, 203,980 cases |
| `branch512_ab_fast_sim` | Full block: 25 residual branches, stalls, malformed packets |
| `branch512_ab_reset_sim`, `branch512_ab_payload_reset_sim` | Six pipeline and two output-buffer reset cases |

Full-block tests use the checked behavioral MAC (`sim/qn_mac_ab_model.sv`) for
speed. Synthesis uses the vendor DSP primitives.

## Native libraries

On ARM64 with GCC:

```sh
sh scripts/build_native.sh     # Citrinet operators -> build/native
sh scripts/build_moonshine.sh  # Moonshine transport -> build/native/libqnc_moonshine.so
```

`-ffp-contract=off` is part of the arithmetic contract. Do not add fast-math
flags. Compare a rebuild against the INT8 CPU graph on the board before
adopting it.

## Hashes

After changing sources, run `python3 scripts/write_manifest.py` to update
`config/assets.json`. This records bytes only; it does not qualify hardware.
