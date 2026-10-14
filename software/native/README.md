# libqnc: native QNC2 host

`libqnc` is the C host library for the base QNC2 cached pointwise engine and its
ioctl 3/4 driver. The first v2 runtime (`../runtime/`) uses it. Later designs
replace it with the ORT custom operators in `../ort_fpga_*`.

For each layer, the library:
- packs the weights once;
- quantizes the activations directly into packet buffers;
- sends bounded RUN batches and checks every response;
- dequantizes straight into the FP32 output.

The arithmetic:
- symmetric INT8 inputs and weights with INT32 sums;
- per-output-channel weight scales and one activation scale per layer;
- nearest-even rounding.

There is no fast-math and no fused multiply-add. On ARM64, NEON handles full
16-frame tiles; build with `-DQNC_FORCE_SCALAR` for a scalar version to compare.

A failed transfer invalidates the host cache and raises an error. Nothing is
replayed or run on the CPU instead.

On the board:

```sh
make CC=gcc CFLAGS='-O3 -mcpu=cortex-a53 -std=c11 -Wall -Wextra -Werror -fno-fast-math -ffp-contract=off'
./test_qnc
python smoke.py --device /dev/qn-tile --output native_smoke.json
```

- **`test_qnc`** checks the arithmetic, batching, corrupt responses and transport
  failures against a callback simulator, so it doesn't use the FPGA.
- **`smoke.py`** runs the same checks on the FPGA.
- **`cross_build.sh`** cross-compiles the library in WSL.
- **`prebuilt/aarch64/`** records the QEMU Cortex-A53 validation of the NEON and
  scalar builds.
