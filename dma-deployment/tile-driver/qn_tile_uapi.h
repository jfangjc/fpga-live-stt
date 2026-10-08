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
#define QN_TILE_MAX_INPUT 32784U
#define QN_TILE_OUTPUT_BYTES 1024U
#endif
