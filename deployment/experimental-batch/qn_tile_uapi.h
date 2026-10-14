/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef QN_TILE_UAPI_H
#define QN_TILE_UAPI_H
#include <linux/ioctl.h>
#include <linux/types.h>
/* Byte buffers; no physical addresses. Same layout for 32/64-bit callers. */
struct qn_tile_request {
	__u64 input_pointer;
	__u64 output_pointer;
	__u32 input_bytes;
	__u32 reserved;
};
#define QN_TILE_RUN _IOW('Q', 1, struct qn_tile_request)
/* Homogeneous packets, each with its own AXI stream TLAST. */
struct qn_tile_batch_request {
	__u64 input_pointer;
	__u64 output_pointer;
	__u32 packet_bytes;
	__u32 count;
};
#define QN_TILE_RUN_BATCH _IOW('Q', 2, struct qn_tile_batch_request)
/* One QNC2 command and one exact-sized QNR2 response. Both flags must be zero. */
struct qn_layer_request {
	__u64 input_pointer;
	__u64 output_pointer;
	__u32 input_bytes;
	__u32 output_bytes;
	__u32 flags;
	__u32 reserved;
};
#define QN_LAYER_EXCHANGE _IOWR('Q', 3, struct qn_layer_request)
/* Homogeneous QNC2 RUN packets; separate stream TLAST per packet. */
struct qn_layer_batch_request {
	__u64 input_pointer;
	__u64 output_pointer;
	__u32 packet_bytes;
	__u32 response_bytes;
	__u32 count;
	__u32 reserved;
};
#define QN_LAYER_RUN_BATCH _IOWR('Q', 4, struct qn_layer_batch_request)
#define QN_LAYER_BATCH_OUTPUT_BYTES (4U * 1024U * 1024U)
#define QN_LAYER_COMMAND_MAGIC 0x32434e51U
#define QN_LAYER_RESPONSE_MAGIC 0x32524e51U
#define QN_LAYER_LOAD 1U
#define QN_LAYER_RUN 2U
#define QN_LAYER_INVALIDATE 3U
#define QN_TILE_MAX_BATCH 128U
#define QN_TILE_MAX_INPUT 32784U
#define QN_TILE_OUTPUT_BYTES 1024U
#define QN_TILE_BATCH_INPUT_BYTES (QN_TILE_MAX_BATCH * QN_TILE_MAX_INPUT)
#define QN_TILE_BATCH_OUTPUT_BYTES (QN_TILE_MAX_BATCH * QN_TILE_OUTPUT_BYTES)
#endif
