# qn_tile driver

Linux 6.8 DMAengine client that exposes the PL accelerator as `/dev/qn-tile`.
This folder is the cached-layer version. It keeps the legacy QNT1 tile ioctls
and adds the QNC2 cached-layer ioctls. Use it only with a QNC2 bitstream.
The QNT1-only driver is in `dma-deployment/tile-driver/` and the batch
version in `dma-batch-update/tile-driver/`.

## Build and load

On the board, with the design's overlay loaded:

```bash
make KDIR=/lib/modules/$(uname -r)/build
sudo insmod qn_tile.ko
ls -l /dev/qn-tile
```

`kernel-build/build_exact.sh` cross-builds against the exact
`6.8.0-1015-xilinx` headers. The module is unsigned; the kernel enables
signatures but does not force them. Remove it with `sudo rmmod qn_tile` after
closing every client.

The protocol validator also builds as a host test:

```bash
gcc -std=c11 -Wall -Wextra -Werror -o /tmp/qn_layer_protocol_test test_layer_protocol.c
/tmp/qn_layer_protocol_test
```

It checks every M=1..1024, every batch count boundary, malformed headers and
the ioctl ABI layout (305,152 bounds checks).

## Hardware binding

| Item | Value |
|---|---|
| Microphone / V1 core (UIO) | 0xA0000000, GIC SPI 89 |
| AXI DMA | 0xA0010000; MM2S SPI 90, S2MM SPI 91; 64-bit addresses, 128-bit streams, HP0 port |
| Reset/status GPIO | 0xA0020000; lines reset 0, busy 1, error 2 |

The device-tree node needs `compatible = "prototype,qn-tile"`,
`dma-names = "tx", "rx"`, `reset-gpios = <&tile_gpio 0 1>` (active low) and
`error-gpios = <&tile_gpio 2 0>`, where `tile_gpio` is the AXI GPIO node. See `software/voice-dma.dts` and
`software/voice-cached.dts`.

## Ioctls

| Ioctl | Number | Use |
|---|---|---|
| `QN_TILE_RUN` | `_IOW('Q', 1)` | One QNT1 tile: `16 + 32*K` bytes in (K ≤ 1024), 1024 bytes out |
| `QN_TILE_RUN_BATCH` | `_IOW('Q', 2)` | Up to 128 QNT1 tiles, each with its own TLAST |
| `QN_LAYER_EXCHANGE` | `0xc0205103` | One QNC2 LOAD, RUN or INVALIDATE |
| `QN_LAYER_RUN_BATCH` | `0xc0205104` | 1–128 RUN packets with the same K, M and tag |

A QNT1 packet is the magic `0x31544e51`, K as u32, eight zero bytes, then K
rows of 16 INT8 inputs and K rows of 16 INT8 weights. The output is 256
INT32 values, time-major 16x16. Bias, scaling and ReLU stay on the host.

Requests are 32 bytes in `qn_tile_uapi.h`: two user pointers, byte counts
and zero reserved fields. No physical addresses are accepted. Every request is
validated before DMA (`qn_layer_protocol.h`), and every response header and
status is checked before results are copied back.

- **Serialization:** one transfer at a time across all file descriptors. RX
  is armed before TX. Each channel has a 5 s timeout.
- **Cache lease:** a successful LOAD records the owning file description,
  K, M and tag. A RUN from another owner, or with a stale tag, returns
  `ESTALE` before DMA. Another client may replace the cache with its own
  LOAD. Legacy tile calls, reset and closing the owner clear the lease.
- **Batch size:** limited by a 133,120-byte response buffer: 2 RUNs at
  M=1024, 4 at 512, 8 at 256, 128 at M≤16.
- **Errors:** `EINVAL` bad request, `EFAULT` bad user buffer, `ETIMEDOUT`
  no completion, `EPROTO` malformed response, `EIO` hardware or DMA error,
  `ENODEV` removed device. Errors terminate both channels and reset the core.
  If termination fails, the instance keeps its buffers and pins the module
  until reboot.
