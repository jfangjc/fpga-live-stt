/* SPDX-License-Identifier: GPL-2.0 */
#ifndef QN_LAYER_PROTOCOL_H
#define QN_LAYER_PROTOCOL_H
/* Included after types, errno and get_unaligned_le32 by kernel or host test. */
#include "qn_tile_uapi.h"
struct qn_layer_command {
	__u32 op, k, m, tag;
};

static inline int qn_layer_batch_bounds(__u32 packet_bytes, __u32 response_bytes,
				      __u32 count)
{
	/* Divide before multiplying: hostile lengths cannot overflow the checks. */
	if (!count || count > QN_TILE_MAX_BATCH || packet_bytes < 32 ||
	    packet_bytes > QN_TILE_MAX_INPUT || response_bytes < 1040 ||
	    response_bytes > QN_LAYER_BATCH_OUTPUT_BYTES / count)
		return -EINVAL;
	return 0;
}

static inline int qn_layer_validate(const void *packet, __u32 input_bytes,
				   __u32 output_bytes, struct qn_layer_command *c)
{
	const unsigned char *h = packet;
	__u32 command, dimensions, groups, expected_input, expected_output;
	if (input_bytes < 16)
		return -EINVAL;
	command = get_unaligned_le32(h + 4);
	dimensions = get_unaligned_le32(h + 8);
	c->op = command & 0xff;
	c->m = command >> 16;
	c->k = dimensions & 0xffff;
	c->tag = get_unaligned_le32(h + 12);
	if (get_unaligned_le32(h) != QN_LAYER_COMMAND_MAGIC ||
	    (command & 0xff00) || (dimensions >> 16))
		return -EINVAL;
	if (c->op == QN_LAYER_INVALIDATE) {
		if (c->k || c->m || c->tag)
			return -EINVAL;
		expected_input = expected_output = 16;
	} else if ((c->op == QN_LAYER_LOAD || c->op == QN_LAYER_RUN) &&
		   c->m >= 1 && c->m <= 1024 && c->k >= 1 && c->k <= 1024 && c->tag) {
		groups = (c->m + 15) / 16;
		expected_input = 16 + c->k * 16 * (c->op == QN_LAYER_LOAD ? groups : 1);
		expected_output = 16 + (c->op == QN_LAYER_RUN ? groups * 1024 : 0);
	} else {
		return -EINVAL;
	}
	return input_bytes == expected_input && output_bytes == expected_output ? 0 : -EINVAL;
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
	if (ret || first->op != QN_LAYER_RUN)
		return -EINVAL;
	for (i = 1; i < count; i++) {
		ret = qn_layer_validate((const unsigned char *)packets + i * packet_bytes,
			packet_bytes, response_bytes, &c);
		if (ret || c.op != QN_LAYER_RUN || c.k != first->k ||
		    c.m != first->m || c.tag != first->tag)
			return -EINVAL;
	}
	return 0;
}
#endif
