#ifndef QNC_H
#define QNC_H
#include <stddef.h>
#include <stdint.h>
/* One context per inference worker. Not thread safe. Return 0 or negative errno. */
typedef struct qnc qnc;
typedef int (*qnc_exchange)(void *, const uint8_t *, uint8_t *, uint32_t, uint32_t, uint32_t, int);
typedef struct { uint64_t ioctls, loads, runs, tx_bytes, rx_bytes; double ioctl_seconds; } qnc_stats;
/* Separate getter preserves original qnc_stats ABI and Python callers. Times
 * are subsets of the pointwise call, not extra costs to add to total time. */
typedef struct { double load_pack_seconds, scan_seconds, run_pack_seconds, unpack_seconds;
 uint64_t mac_issue_cycles,input_stall_cycles,output_stall_cycles,active_cycles; } qnc_profile;
qnc *qnc_open(const char *path);
/* Callback transport is for protocol simulation; never reports hardware execution. */
qnc *qnc_create(qnc_exchange exchange, void *opaque);
void qnc_close(qnc *ctx);
int qnc_load(qnc *ctx, const int8_t *weights, unsigned m, unsigned k);
int qnc_load_quant(qnc *ctx, const int8_t *weights, unsigned m, unsigned k,
                   const int32_t *bias, const int32_t *multiplier,
                   const uint8_t *shift, uint8_t zero);
int qnc_run_quant(qnc *ctx, const int8_t *x, size_t times, uint8_t *y);
int qnc_run_bulk(qnc *ctx, const uint8_t *x, size_t times, uint8_t *y);
int qnc_invalidate(qnc *ctx);
int qnc_run_i8(qnc *ctx, const int8_t *x, size_t times, int32_t *y);
/* X[K,T], Y[M,T], contiguous. Whole-layer dynamic symmetric quantization,
 * nearest-even division rounding, saturation [-127,127]. No bias or activation. */
int qnc_run_f32(qnc *ctx, const float *x, size_t times, const float *weight_scales,
                float *y, float *activation_scale);
void qnc_get_stats(const qnc *ctx, qnc_stats *stats);
void qnc_get_profile(const qnc *ctx, qnc_profile *profile);
#endif
