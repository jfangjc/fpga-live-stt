/* SPDX-License-Identifier: MIT
 * FP32 channelwise 1D cross-correlation for QuartzNet CPU depthwise nodes.
 * Build with -ffp-contract=off; hardware pointwise execution is independent.
 */
#include <stddef.h>
#include <stdint.h>
#include <errno.h>
#include <pthread.h>
#if defined(__aarch64__) && defined(__ARM_NEON)
#include <arm_neon.h>
#endif

struct job {
    const float *x, *w, *b;
    float *y;
    size_t c, t, k, out, stride, dilation, left, extent;
    size_t begin, end;
};

static int product(size_t a, size_t b, size_t *result)
{
    if (a && b > SIZE_MAX / a) return 0;
    *result = a * b;
    return 1;
}

static int span(const void *p, size_t bytes, uintptr_t *end)
{
    uintptr_t start = (uintptr_t)p;
    if (bytes > UINTPTR_MAX - start) return 0;
    *end = start + bytes;
    return 1;
}

static float scalar(const struct job *j, const float *x,
                    const float *w, size_t o, float bias)
{
    /* Match ordinary unfused cross-correlation: reduce K, then add bias. */
    float a = 0.0f;
    size_t virtual_index = o * j->stride;
    for (size_t k = 0; k < j->k; ++k) {
        float value = virtual_index >= j->left && virtual_index - j->left < j->t
                    ? x[virtual_index - j->left] : 0.0f;
        a = a + value * w[k];
        virtual_index += j->dilation;
    }
    return a + bias;
}

static void *work(void *opaque)
{
    const struct job *j = opaque;
    for (size_t channel = j->begin; channel < j->end; ++channel) {
        const float *x = j->x + channel * j->t;
        const float *w = j->w + (channel % j->c) * j->k;
        float *y = j->y + channel * j->out;
        float bias = j->b ? j->b[channel % j->c] : 0.0f;
        size_t o = 0;
#if defined(__aarch64__) && defined(__ARM_NEON)
        if (j->stride == 1) {
            /* Scalar padding boundary, then four independent output vectors. */
            while (o < j->out && o < j->left) {
                y[o] = scalar(j, x, w, o, bias);
                ++o;
            }
            while (j->out - o >= 16 && o >= j->left) {
                size_t base = o - j->left;
                if (base >= j->t || j->extent > j->t - base ||
                    j->t - base - j->extent < 15) break;
                float32x4_t a0 = vdupq_n_f32(0.0f);
                float32x4_t a1 = a0, a2 = a0, a3 = a0;
                for (size_t k = 0; k < j->k; ++k) {
                    const float *p = x + base + k * j->dilation;
                    float32x4_t weight = vdupq_n_f32(w[k]);
                    a0 = vaddq_f32(a0, vmulq_f32(vld1q_f32(p), weight));
                    a1 = vaddq_f32(a1, vmulq_f32(vld1q_f32(p + 4), weight));
                    a2 = vaddq_f32(a2, vmulq_f32(vld1q_f32(p + 8), weight));
                    a3 = vaddq_f32(a3, vmulq_f32(vld1q_f32(p + 12), weight));
                }
                float32x4_t b = vdupq_n_f32(bias);
                vst1q_f32(y + o, vaddq_f32(a0, b));
                vst1q_f32(y + o + 4, vaddq_f32(a1, b));
                vst1q_f32(y + o + 8, vaddq_f32(a2, b));
                vst1q_f32(y + o + 12, vaddq_f32(a3, b));
                o += 16;
            }
        }
#endif
        for (; o < j->out; ++o) y[o] = scalar(j, x, w, o, bias);
    }
    return NULL;
}

int qn_depthwise_f32(const float *x, const float *w, const float *b, float *y,
                    size_t n, size_t c, size_t t, size_t k, size_t stride,
                    size_t dilation, size_t pad_left, size_t pad_right,
                    unsigned threads)
{
    size_t extent, padded, out, channels, nx, nw, ny, bx, bw, by, bb;
    uintptr_t xe, we, ye, be = 0;
    struct job jobs[4];
    pthread_t ids[4];
    int launched[4] = {0};
    if (!x || !w || !y || !n || !c || !t || !k || !stride || !dilation)
        return -EINVAL;
    if (!product(k - 1, dilation, &extent) || extent == SIZE_MAX)
        return -EOVERFLOW;
    ++extent;
    if (pad_left > SIZE_MAX - t || pad_right > SIZE_MAX - t - pad_left)
        return -EOVERFLOW;
    padded = t + pad_left + pad_right;
    if (padded < extent) return -EINVAL;
    out = (padded - extent) / stride + 1;
    if (!product(n, c, &channels) || !product(channels, t, &nx) ||
        !product(c, k, &nw) || !product(channels, out, &ny) ||
        !product(nx, sizeof(float), &bx) || !product(nw, sizeof(float), &bw) ||
        !product(ny, sizeof(float), &by) || !product(c, sizeof(float), &bb) ||
        bx > PTRDIFF_MAX || bw > PTRDIFF_MAX || by > PTRDIFF_MAX || bb > PTRDIFF_MAX)
        return -EOVERFLOW;
    if ((uintptr_t)x % _Alignof(float) || (uintptr_t)w % _Alignof(float) ||
        (uintptr_t)y % _Alignof(float) || (b && (uintptr_t)b % _Alignof(float)))
        return -EINVAL;
    if (!span(x, bx, &xe) || !span(w, bw, &we) || !span(y, by, &ye) ||
        (b && !span(b, bb, &be))) return -EOVERFLOW;
    if (((uintptr_t)y < xe && (uintptr_t)x < ye) ||
        ((uintptr_t)y < we && (uintptr_t)w < ye) ||
        (b && (uintptr_t)y < be && (uintptr_t)b < ye)) return -EINVAL;
    /* Avoid scalar index overflow on the post-final iteration increment. */
    if (padded > SIZE_MAX - dilation) return -EOVERFLOW;
    if (threads < 1) threads = 1;
    if (threads > 4) threads = 4;
    if (channels < threads) threads = (unsigned)channels;
    size_t begin = 0, chunk = channels / threads, extra = channels % threads;
    for (unsigned i = 0; i < threads; ++i) {
        size_t count = chunk + (i < extra);
        jobs[i] = (struct job){x, w, b, y, c, t, k, out, stride, dilation,
                             pad_left, extent, begin, begin + count};
        begin += count;
    }
    /* Failed thread creation falls back to synchronous work for that range. */
    for (unsigned i = 1; i < threads; ++i) {
        if (!pthread_create(&ids[i], NULL, work, &jobs[i])) launched[i] = 1;
        else work(&jobs[i]);
    }
    work(&jobs[0]);
    for (unsigned i = 1; i < threads; ++i)
        if (launched[i]) pthread_join(ids[i], NULL);
    return 0;
}
