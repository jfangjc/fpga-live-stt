# Kernel drivers

The bulk and branch images use different `qn_tile` modules with the same
module name, so only one can be loaded at a time. Both, with their sources,
come from the dependency archive ([dependencies.md](dependencies.md)).

| Image | Used by | Source | Prebuilt module |
|---|---|---|---|
| `asr-v3-bulk` | Moonshine, Citrinet rollback | `drivers/bulk` | `drivers/prebuilt/6.8.0-1036-xilinx/bulk/qn_tile.ko` |
| `asr-v3-branch512-ab166` | Citrinet inference | `drivers/branch` | `drivers/prebuilt/6.8.0-1036-xilinx/branch/qn_tile.ko` |

## Rebuild for another kernel

You need the headers and build configuration of the exact running Xilinx
kernel. A generic Ubuntu kernel with a similar number does not work.

```sh
test -f /lib/modules/$(uname -r)/build/Makefile
make -C drivers/bulk
make -C drivers/branch
modinfo -F vermagic drivers/bulk/qn_tile.ko
modinfo -F vermagic drivers/branch/qn_tile.ko
```

- The Makefiles accept `KDIR=/path/to/kernel/build`.
- Put the reviewed modules under `drivers/prebuilt/<kernel-release>/bulk` and
  `branch`, update their hashes in `config/dependencies.json`, then run
  `python3 scripts/write_manifest.py`.
- Test loading, protocol parameters, physical counters, CPU parity and
  rollback on the new kernel. Only `6.8.0-1036-xilinx` has been tested.
