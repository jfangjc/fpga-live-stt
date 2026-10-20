/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef QN_STREAM_REGISTERED_H
#define QN_STREAM_REGISTERED_H
#include "qn_tile_uapi.h"
#include "qn_cache_protocol.h"
/* Immutable prefix registration; handle is an opaque, per-open identifier. */
struct qn_stream_register {
    __u64 prefix_pointer, handle;
    __u32 prefix_bytes, flags;
    __u64 reserved;
};
struct qn_stream_run {
    __u64 input_pointer, output_pointer, handle;
    __u32 times, valid_times, input_bytes, output_bytes;
};
#define QN_STREAM_REGISTER _IOWR('Q',6,struct qn_stream_register)
#define QN_STREAM_RUN _IOWR('Q',7,struct qn_stream_run)
#define QN_STREAM_RELEASE _IOW('Q',8,__u64)
#define QN_STREAM_PROGRAMS 64U
#define QN_STREAM_MEMORY_LIMIT (32U*1024U*1024U)
static inline __u32 qn_stream_prefix_bytes(__u32 n) {
    return 32+n*16+n*QN_STREAM_STAGE_BYTES+(n-1)*256;
}
static inline int qn_stream_run_bounds(const struct qn_stream_run *r) {
    if(!r->handle || !r->times || r->times>256 || r->valid_times>r->times ||
       r->input_bytes!=256*((r->times+15)/16)*16 ||
       r->output_bytes!=r->input_bytes+32)return -EINVAL;
    return 0;
}
#endif
