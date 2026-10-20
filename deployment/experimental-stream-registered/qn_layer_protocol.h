/* SPDX-License-Identifier: GPL-2.0 */
#ifndef QN_LAYER_PROTOCOL_H
#define QN_LAYER_PROTOCOL_H
/* Included after types, errno and get_unaligned_le32 by kernel or host test. */
#include "qn_tile_uapi.h"
struct qn_layer_command {
	__u32 op, k, m, tag, times;
};

static inline int qn_layer_batch_bounds(__u32 packet_bytes, __u32 response_bytes,
				      __u32 count)
{
	/* Divide before multiplying: hostile lengths cannot overflow the checks. */
	if (!count || count > QN_TILE_MAX_BATCH || packet_bytes < 32 ||
	    packet_bytes > QN_TILE_MAX_INPUT || response_bytes < 272 ||
	    response_bytes > QN_LAYER_BATCH_OUTPUT_BYTES / count)
		return -EINVAL;
	return 0;
}

static inline int qn_layer_validate(const void *packet, __u32 input_bytes,
				   __u32 output_bytes, struct qn_layer_command *c)
{
	const unsigned char *h = packet;
	__u32 command, dimensions, groups = 0, expected_input, expected_output;
	if (input_bytes < 16)
		return -EINVAL;
	command = get_unaligned_le32(h + 4);
	dimensions = get_unaligned_le32(h + 8);
	c->op = command & 0xff;
	c->m = command >> 16;
	c->k = dimensions & 0xffff;
	c->tag = get_unaligned_le32(h + 12);
	c->times = dimensions >> 16;
	if (get_unaligned_le32(h) != QN_LAYER_COMMAND_MAGIC ||
	    (command & 0xff00) || (c->op != QN_LAYER_RUN_BULK && c->op != 8 && c->times))
		return -EINVAL;
	if (c->op == QN_LAYER_INVALIDATE) {
		if (c->k || c->m || c->tag)
			return -EINVAL;
		expected_input = expected_output = 16;
    } else if ((c->op == QN_LAYER_LOAD || c->op == QN_LAYER_RUN ||
                c->op == QN_LAYER_LOAD_QUANT || c->op == QN_LAYER_RUN_QUANT) &&
		   c->m >= 1 && c->m <= 1024 && c->k >= 1 && c->k <= 1024 && c->tag) {
		groups = (c->m + 15) / 16;
        expected_input = 16 + c->k * 16 *
            ((c->op == QN_LAYER_LOAD || c->op == QN_LAYER_LOAD_QUANT) ? groups : 1);
        if (c->op == QN_LAYER_LOAD_QUANT)
            expected_input += groups * 16 * 16;
        expected_output = 16 + (c->op == QN_LAYER_RUN ? groups * 1024 :
                               c->op == QN_LAYER_RUN_QUANT ? groups * 256 : 0);
	} else if (c->op == 7 && c->k >= 1 && c->k <= 1024 && c->m >= 11 && c->m <= 21 && (c->m & 1) && c->tag) {
        expected_input = 16 + c->k * 48;
        expected_output = 16;
    } else if ((c->op == QN_LAYER_RUN_BULK || c->op == 8) && c->k >= 1 && c->k <= 1024 &&
               c->m >= 1 && c->m <= 1024 && c->tag && c->times >= 1 && c->times <= 256) {
        __u32 tiles = (c->times + 15) / 16;
        if (c->k > 65536U / tiles)
            return -EINVAL;
        groups = (c->m + 15) / 16;
        expected_input = (c->op == 8 ? 32 : 16) + tiles * c->k * 16;
        expected_output = 32 + tiles * groups * 256;
        if (expected_output > QN_LAYER_BATCH_OUTPUT_BYTES)
            return -EINVAL;
	} else {
		return -EINVAL;
	}
	if (input_bytes != expected_input || output_bytes != expected_output)
		return -EINVAL;
    if (c->op == 7) {
        __u32 i;
        for (i = 0; i < c->k; ++i) {
            const unsigned char *w = h + 16 + i * 32;
            const unsigned char *p = h + 16 + c->k * 32 + i * 16;
            __u32 flags = get_unaligned_le32(p + 8);
            for (__u32 b = c->m; b < 32; ++b) if (w[b]) return -EINVAL;
            if (
                (get_unaligned_le32(p + 4) >> 31) || (flags & 0xffff00c0U) ||
                !(flags & 63) || (flags & 63) == 63 || get_unaligned_le32(p + 12) > 255)
                return -EINVAL;
        }
    }
    if (c->op == 8 && (get_unaligned_le32(h + 16) > c->times ||
        get_unaligned_le32(h + 20) || get_unaligned_le32(h + 24) || get_unaligned_le32(h + 28))) {
        return -EINVAL;
    }
	if (c->op == QN_LAYER_LOAD_QUANT) {
		__u32 i;
		const unsigned char *params = h + 16 + groups * c->k * 16;
		for (i = 0; i < groups * 16; ++i) {
			__u32 mult = get_unaligned_le32(params + i * 16 + 4);
			__u32 flags = get_unaligned_le32(params + i * 16 + 8);
			if ((mult >> 31) || (flags & 0xffff00c0U) ||
			    !(flags & 63) || (flags & 63) == 63 ||
			    get_unaligned_le32(params + i * 16 + 12))
				return -EINVAL;
		}
	}
	return 0;
}

static inline int qn_layer_validate_batch(const void *packets, __u32 packet_bytes,
		__u32 response_bytes, __u32 count, struct qn_layer_command *first)
{
	struct qn_layer_command c;
	__u32 i;
	int ret = qn_layer_batch_bounds(packet_bytes, response_bytes, count);
	if (ret)
		return ret;
	ret = qn_layer_validate(packets, packet_bytes, response_bytes, first);
    if (ret || (first->op != QN_LAYER_RUN && first->op != QN_LAYER_RUN_QUANT))
		return -EINVAL;
	for (i = 1; i < count; i++) {
		ret = qn_layer_validate((const unsigned char *)packets + i * packet_bytes,
			packet_bytes, response_bytes, &c);
		if (ret || c.op != first->op || c.k != first->k ||
		    c.m != first->m || c.tag != first->tag)
			return -EINVAL;
	}
	return 0;
}
#endif
