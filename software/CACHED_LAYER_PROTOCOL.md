# QNC2 cached pointwise protocol

The Verilog `qn_cached_axis` and matching Linux driver implement signed INT8
pointwise multiplication with unscaled signed INT32 output. They preserve
the previous QNT1 arithmetic. Bias, FP32 scaling and quantization remain in
the host graph. Every RUN computes 16 time positions across all output
channels using one previously loaded layer. Host software pads unused lanes
with zero and crops results.

All AXI-stream beats are 128 bits. Words and signed INT32 values are little
endian. TX TLAST terminates exactly the specified packet. RX TLAST terminates
the entire response, including all output groups. Output is held stable while
backpressured. Reset returns to header state and invalidates cached weights.

| Request word | Meaning |
|---|---|
| 0 | `0x32434e51` (QNC2) |
| 1 | bits7:0 opcode; bits15:8 zero; bits31:16 output channels M |
| 2 | bits15:0 reduction channels K; bits31:16 zero |
| 3 | nonzero cache tag |

LOAD=1 and RUN=2 require K/M in 1..1024. INVALIDATE=3 requires K/M/tag zero
and carries no payload. RUN requires the exact tag, K and M of a committed
LOAD. Tags identify layer contents; applications must not reuse a tag for
different weights while relying on the old load.

Let G=ceil(M/16):

- LOAD: weights in `[G,K,16]` signed byte order, 16+16*G*K bytes total.
- RUN: inputs in `[K,16]` signed byte order, 16+16*K bytes total.
- INVALIDATE: 16 bytes total.

Every QNC2 response begins with four words: `0x32524e51` (QNR2), status,
`K | (M << 16)`, and the requested tag. Status0 means success, 1 invalid
header, 2 packet framing error, 3 cache mismatch. LOAD and INVALIDATE return
only this 16-byte acknowledgement. RUN returns another 1024*G bytes in
`[G,16 times,16 channels]` signed INT32 order. There is no implicit cropping.

A valid-dimension RUN with a framing/cache error returns the expected full
length with zero data. An invalid header returns only the acknowledgement;
the driver rejects such requests before DMA, so its expected RX length
remains unambiguous. All hardware errors invalidate the cache. Bad packets
drain until TX TLAST; a missing TLAST requires the driver's timeout/reset
recovery. An incomplete LOAD is never committed.

The cache reserves 64 output groups with a fixed K stride1024. Its 1MiB
logical weight storage maps to UltraRAM; the input block uses BRAM. Memory
contents are not reset, but cache validity and packet bounds prevent stale
contents from being used. Reset, INVALIDATE and any legacy QNT1 packet
invalidate the cache. QNT1 still returns its original 1024-byte tile and
does not include a QNR2 header.

The Linux ioctl is `_IOWR('Q',3,32)` = `0xc0205103`: two u64 userspace
pointers, u32 TX bytes, u32 RX bytes, u32 zero flags and u32 zero reserved.
The driver serializes exchanges, validates exact sizes and response identity,
and records the cache owner as an open file description. Another process may
replace the cache; a stale RUN returns ESTALE before DMA. Sharing one FD
between threads requires host synchronization across LOAD/RUN sequences.
Exceptions must be surfaced; the client does not silently replay or fall
back to CPU execution.

LOAD uses one ioctl. RUN can also use `_IOWR('Q',4,32)` = `0xc0205104`:
two u64 userspace pointers, then u32 packet bytes, u32 response bytes per
packet, u32 count and u32 zero reserved. It carries 1..128 consecutive RUN
packets with identical K/M/tag. Each packet retains its own TLAST and QNR2
response. The driver checks every packet before DMA and every response
after completion. A batch holds the driver's mutex for the complete chain.
LOAD and INVALIDATE cannot appear inside a batch.

The RX allocation bounds the aggregate response to 133120 bytes. Automatic
client batching therefore supports 2 RUNs at M=1024, 4 at M=512, 8 at M=256,
and 128 at M=16. The existing legacy batch ABI is unchanged. Batching reduces
ioctl/interrupt overhead; actual throughput still requires board measurement.
