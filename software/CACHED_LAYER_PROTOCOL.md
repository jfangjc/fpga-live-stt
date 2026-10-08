# QNC2 cached-layer protocol

`rtl/qn_cached_axis.v` computes signed INT8 pointwise products with unscaled
INT32 output, the same arithmetic as QNT1. Bias, FP32 scaling and
quantization stay on the host. Each RUN computes 16 time positions across all
output channels of the currently loaded layer. The host zero-pads unused
lanes and crops the results.

## Framing

- AXI-stream beats are 128 bits; words are little endian.
- TX TLAST ends exactly one request packet. RX TLAST ends the whole response.
- Reset returns to the header state and invalidates the cache.

## Request

| Word | Meaning |
|---|---|
| 0 | `0x32434e51` (QNC2) |
| 1 | bits7:0 opcode; bits15:8 zero; bits31:16 output channels M |
| 2 | bits15:0 reduction channels K; bits31:16 zero |
| 3 | Nonzero cache tag |

With G = ceil(M/16):

| Opcode | K, M, tag | Payload | Total bytes |
|---|---|---|---|
| LOAD = 1 | 1..1024, nonzero tag | Weights `[G, K, 16]` INT8 | 16 + 16·G·K |
| RUN = 2 | Must match the committed LOAD | Inputs `[K, 16]` INT8 | 16 + 16·K |
| INVALIDATE = 3 | All zero | None | 16 |

A tag identifies layer contents. Do not reuse a tag for different weights.

## Response

Four words: `0x32524e51` (QNR2), status, `K | (M << 16)`, tag.

| Status | Meaning |
|---|---|
| 0 | Success |
| 1 | Invalid header |
| 2 | Framing error |
| 3 | Cache mismatch |

LOAD and INVALIDATE return only the 16-byte header. RUN adds 1024·G bytes of
INT32 in `[G, 16 times, 16 channels]` order.

## Errors

- A RUN with valid dimensions but a framing or cache error returns the full
  expected length with zero data, so DMA lengths always match.
- An invalid header returns only the header. The driver rejects these before
  DMA.
- Any hardware error invalidates the cache. Bad packets drain until TX TLAST.
  An incomplete LOAD is never committed.

## Cache

64 output groups with a fixed K stride of 1024: 1 MiB of weights in UltraRAM.
The input block is in BRAM. Reset, INVALIDATE and any legacy QNT1 packet
invalidate the cache. QNT1 still returns its original 1024-byte tile with no
QNR2 header.

## Linux ioctls

| Ioctl | Request (32 bytes) |
|---|---|
| `_IOWR('Q', 3, 32)` = `0xc0205103` | u64 TX pointer, u64 RX pointer, u32 TX bytes, u32 RX bytes, u32 flags (0), u32 reserved (0) |
| `_IOWR('Q', 4, 32)` = `0xc0205104` | u64 TX pointer, u64 RX pointer, u32 packet bytes, u32 response bytes per packet, u32 count, u32 reserved (0) |

The batch ioctl carries 1..128 consecutive RUN packets with the same K, M and
tag. Each packet keeps its own TLAST and QNR2 response. LOAD and INVALIDATE
cannot be batched. The aggregate response is limited to 133,120 bytes, so
the client sends 2 RUNs per batch at M=1024, 4 at 512, 8 at 256 and 128 at
M=16. Driver behaviour (leases, errors) is in
[tile-driver/README.md](tile-driver/README.md).
