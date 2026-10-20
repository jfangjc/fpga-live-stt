/* Host tests exercise the exact validator used before DMA submission. */
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <linux/types.h>
static uint32_t get_unaligned_le32(const void *p)
{
	const unsigned char *b = p;
	return b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16 | (uint32_t)b[3] << 24;
}
#include "qn_layer_protocol.h"
static void put32(unsigned char *p, uint32_t v)
{
	for (unsigned int i = 0; i < 4; ++i)
		p[i] = v >> (i * 8);
}
static void header(unsigned char *h, unsigned int op, unsigned int k,
		   unsigned int m, unsigned int tag)
{
	put32(h, QN_LAYER_COMMAND_MAGIC);
	put32(h + 4, op | m << 16);
	put32(h + 8, k);
	put32(h + 12, tag);
}
int main(void)
{
	unsigned char storage[17], *h = storage + 1;
	struct qn_layer_command c;
	unsigned int checks = 0;
	assert(sizeof(struct qn_layer_request) == 32);
	assert(QN_LAYER_EXCHANGE == 0xc0205103UL);
	assert(sizeof(struct qn_layer_batch_request) == 32);
	assert(QN_LAYER_RUN_BATCH == 0xc0205104UL);
	assert(QN_LAYER_BATCH_OUTPUT_BYTES == 4U * 1024U * 1024U);
	for (unsigned int m = 1; m <= 1024; m++) {
		for (unsigned int k = 1; k <= 1024; k += 31) {
			unsigned int groups = (m + 15) / 16;
			unsigned int in = 16 + groups * k * 16;
			unsigned int out = 16 + groups * 1024;
			header(h, QN_LAYER_LOAD, k, m, 42);
			assert(!qn_layer_validate(h, in, 16, &c));
			assert(c.k == k && c.m == m && c.tag == 42);
			assert(qn_layer_validate(h, in - 1, 16, &c) == -EINVAL);
			assert(qn_layer_validate(h, in, 17, &c) == -EINVAL);
			header(h, QN_LAYER_RUN, k, m, 42);
			assert(!qn_layer_validate(h, 16 + k * 16, out, &c));
			assert(qn_layer_validate(h, 16 + k * 16, out - 1, &c) == -EINVAL);
			checks += 5;
		}
	}
	header(h, QN_LAYER_LOAD, 1024, 1024, UINT32_MAX);
	assert(!qn_layer_validate(h, 1048592, 16, &c));
	header(h, QN_LAYER_RUN, 1024, 1024, UINT32_MAX);
	assert(!qn_layer_validate(h, 16400, 65552, &c));
	for (unsigned int op = 0; op <= 255; op++) {
		header(h, op, 1, 1, 1);
		if (op != QN_LAYER_LOAD && op != QN_LAYER_RUN)
			assert(qn_layer_validate(h, 32, 16, &c) == -EINVAL);
	}
	header(h, QN_LAYER_INVALIDATE, 0, 0, 0);
	assert(!qn_layer_validate(h, 16, 16, &c));
	assert(qn_layer_validate(h, 15, 16, &c) == -EINVAL);
	for (unsigned int word = 0; word < 4; word++) {
		header(h, QN_LAYER_INVALIDATE, 0, 0, 0);
		h[word * 4] ^= 0x80;
		assert(qn_layer_validate(h, 16, 16, &c) == -EINVAL);
	}
	for (unsigned int bad = 0; bad <= 1025; bad += 1025) {
		header(h, QN_LAYER_RUN, bad, 1, 1);
		assert(qn_layer_validate(h, 32, 1040, &c) == -EINVAL);
		header(h, QN_LAYER_RUN, 1, bad, 1);
		assert(qn_layer_validate(h, 32, 1040, &c) == -EINVAL);
	}
	header(h, QN_LAYER_RUN, 1, 1, 0);
	assert(qn_layer_validate(h, 32, 1040, &c) == -EINVAL);
	header(h, QN_LAYER_RUN, 1, 1, 1);
	h[5] = 1;
	assert(qn_layer_validate(h, 32, 1040, &c) == -EINVAL);
	header(h, QN_LAYER_RUN, 1, 1, 1);
	h[10] = 1;
	assert(qn_layer_validate(h, 32, 1040, &c) == -EINVAL);
	for (unsigned int m = 1; m <= 1024; m++) {
		unsigned int response = 16 + ((m + 15) / 16) * 1024;
		unsigned int max_count = QN_LAYER_BATCH_OUTPUT_BYTES / response;
		for (unsigned int count = 1; count <= 128; count++) {
			int expected = count <= max_count ? 0 : -EINVAL;
			assert(qn_layer_batch_bounds(16400, response, count) == expected);
			checks++;
		}
	}
	assert(!qn_layer_batch_bounds(32, 1040, 128));
	assert(!qn_layer_batch_bounds(16400, 65552, 2));
	assert(!qn_layer_batch_bounds(16400, 65552, 63));
	assert(qn_layer_batch_bounds(16400, 65552, 64) == -EINVAL);
	assert(qn_layer_batch_bounds(16400, 1040, 0) == -EINVAL);
	assert(qn_layer_batch_bounds(16400, 1040, 129) == -EINVAL);
	assert(qn_layer_batch_bounds(UINT32_MAX, 1040, 1) == -EINVAL);
	assert(qn_layer_batch_bounds(32, UINT32_MAX, 128) == -EINVAL);
	assert(qn_layer_batch_bounds(31, 1040, 1) == -EINVAL);
	assert(qn_layer_batch_bounds(32, 271, 1) == -EINVAL);
	{
		unsigned char batch[32 * 128];
		for (unsigned int i = 0; i < 128; i++)
			header(batch + i * 32, QN_LAYER_RUN, 1, 1, 42);
		assert(!qn_layer_validate_batch(batch, 32, 1040, 128, &c));
		/* A malformed final descriptor must reject the entire chain. */
		header(batch + 127 * 32, QN_LAYER_RUN, 1, 1, 43);
		assert(qn_layer_validate_batch(batch, 32, 1040, 128, &c) == -EINVAL);
		header(batch + 127 * 32, QN_LAYER_LOAD, 1, 1, 42);
		assert(qn_layer_validate_batch(batch, 32, 1040, 128, &c) == -EINVAL);
		header(batch + 127 * 32, QN_LAYER_RUN, 1, 2, 42);
		assert(qn_layer_validate_batch(batch, 32, 1040, 128, &c) == -EINVAL);
		header(batch + 127 * 32, QN_LAYER_RUN, 2, 1, 42);
		assert(qn_layer_validate_batch(batch, 32, 1040, 128, &c) == -EINVAL);
		header(batch, QN_LAYER_LOAD, 1, 1, 42);
		assert(qn_layer_validate_batch(batch, 32, 16, 1, &c) == -EINVAL);
	}
	for (unsigned int m = 1; m <= 1024; m += 255) {
		unsigned int k = 256, groups = (m + 15) / 16;
		unsigned int bytes = 16 + groups * k * 16 + groups * 256;
		unsigned char *load = calloc(1, bytes);
		assert(load);
		header(load, QN_LAYER_LOAD_QUANT, k, m, 123);
		unsigned char *params = load + 16 + groups * k * 16;
		for (unsigned int i = 0; i < groups * 16; ++i) {
			put32(params + i * 16, 0x80000000U); /* signed bias is allowed */
			put32(params + i * 16 + 4, 1073741824);
			put32(params + i * 16 + 8, 31 | (255 << 8));
		}
		assert(!qn_layer_validate(load, bytes, 16, &c));
		assert(qn_layer_validate(load, bytes - 1, 16, &c) == -EINVAL);
		unsigned char *last = params + (groups * 16 - 1) * 16;
		put32(last + 8, 0); assert(qn_layer_validate(load, bytes, 16, &c) == -EINVAL);
		put32(last + 8, 63); assert(qn_layer_validate(load, bytes, 16, &c) == -EINVAL);
		put32(last + 8, 31 | (255 << 8) | 0x10000); assert(qn_layer_validate(load, bytes, 16, &c) == -EINVAL);
		put32(last + 8, 31); put32(last + 4, 0x80000000U); assert(qn_layer_validate(load, bytes, 16, &c) == -EINVAL);
		put32(last + 4, 1); put32(last + 12, 1); assert(qn_layer_validate(load, bytes, 16, &c) == -EINVAL);
		free(load);
	}
	{
		unsigned char batch[32 * 128];
		for (unsigned int i=0;i<128;++i) header(batch+i*32, QN_LAYER_RUN_QUANT,1,17,456);
		assert(!qn_layer_validate_batch(batch,32,528,128,&c));
		assert(qn_layer_validate_batch(batch,32,529,128,&c)==-EINVAL);
		header(batch+127*32,QN_LAYER_RUN,1,17,456);
		assert(qn_layer_validate_batch(batch,32,528,128,&c)==-EINVAL);
	}
	printf("PASS: %u raw bounds checks plus fused quantized payload, malformed final parameters, mixed commands and ABI checks\n", checks);
	return 0;
}
