"""Deterministic INT8/INT32 convolution and Q31 requantization reference.

Int64 intermediates detect INT32 overflow rather than silently wrapping.
The graph interpreter keeps global SE MLP/gates in FP32; activation boundaries
after masking, convolution, residual Add, SE Mul and ReLU use calibrated INT8.
This is a numerical oracle, never a hardware performance simulator.
"""
import numpy as np
from onnx.reference import ReferenceEvaluator
from onnx.reference.op_run import OpRun


def quantize(x, scale):
    x = np.asarray(x)
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(scale)) or np.any(np.asarray(scale) <= 0):
        raise ValueError('Nonfinite tensor or invalid scale')
    return np.clip(np.rint(x.astype(np.float64) / scale), -127, 127).astype(np.int8)


def round_shift_even(x, shift):
    """Signed nearest-even right shift. Caller bounds the INT64 product."""
    x = np.asarray(x, dtype=np.int64)
    if not 1 <= shift <= 62:
        raise ValueError('Right shift must be in 1..62')
    divisor = np.int64(1 << shift)
    quotient, remainder = np.divmod(x, divisor)
    half = divisor // 2
    return quotient + ((remainder > half) | ((remainder == half) & ((quotient & 1) != 0)))


def requantize(accumulator, ratio):
    acc = np.asarray(accumulator, dtype=np.int64)
    if np.any(acc < -(1 << 31)) or np.any(acc > (1 << 31) - 1):
        raise OverflowError('INT32 accumulator overflow')
    ratios = np.broadcast_to(np.asarray(ratio, dtype=np.float64), (acc.shape[1],))
    result = np.empty_like(acc, dtype=np.int8)
    for c, value in enumerate(ratios):
        if not np.isfinite(value) or value <= 0:
            raise ValueError('Invalid requantization ratio')
        if value <= 2.0**-32:
            # Even the largest-magnitude INT32 input rounds to zero (tie -> even).
            result[:, c, :] = 0
            continue
        fraction, exponent = np.frexp(value)
        multiplier = int(np.rint(fraction * (1 << 31)))
        if multiplier == 1 << 31:
            multiplier //= 2; exponent += 1
        shift = 31 - int(exponent)
        if not 1 <= shift <= 62:
            raise ValueError('Ratio outside supported Q31 shift range')
        rounded = round_shift_even(acc[:, c, :] * multiplier, shift)
        result[:, c, :] = np.clip(rounded, -127, 127).astype(np.int8)
    return result


def conv1d(x, weights, bias=None, stride=1, pads=(0, 0), dilation=1, group=1):
    """Exact grouped NCT signed INT8 cross-correlation, INT32 checked output."""
    x, weights = np.asarray(x), np.asarray(weights)
    if x.dtype != np.int8 or weights.dtype != np.int8 or x.ndim != 3 or weights.ndim != 3:
        raise ValueError('Expected INT8 NCT and MCK')
    n, channels, frames = x.shape
    outputs, per_group, kernel = weights.shape
    if (group < 1 or stride < 1 or dilation < 1 or min(pads) < 0 or channels % group
            or outputs % group or per_group != channels // group):
        raise ValueError('Invalid convolution geometry')
    length = (frames + sum(pads) - dilation * (kernel - 1) - 1) // stride + 1
    if length < 1:
        raise ValueError('Empty convolution output')
    padded = np.pad(x.astype(np.int64), ((0, 0), (0, 0), pads))
    w = weights.astype(np.int64)
    result = np.zeros((n, outputs, length), dtype=np.int64)
    # Depthwise avoids hundreds of tiny matrix products.
    if group == channels == outputs and per_group == 1:
        for k in range(kernel):
            result += padded[:, :, k*dilation:k*dilation + length*stride:stride] * w[:, 0, k][None, :, None]
    else:
        width = outputs // group
        for g in range(group):
            for k in range(kernel):
                inputs = padded[:, g*per_group:(g+1)*per_group,
                                k*dilation:k*dilation + length*stride:stride]
                result[:, g*width:(g+1)*width] += w[g*width:(g+1)*width, :, k] @ inputs
    if bias is not None:
        b = np.asarray(bias)
        if b.dtype != np.int32 or b.shape != (outputs,):
            raise ValueError('Expected per-output INT32 bias')
        result += b[None, :, None]
    if np.any(result < -(1 << 31)) or np.any(result > (1 << 31) - 1):
        raise OverflowError('INT32 convolution overflow')
    return result.astype(np.int32)


def conv_parameters(weights, bias, input_scale):
    sw = np.max(np.abs(weights), axis=(1, 2)).astype(np.float64) / 127
    sw[sw == 0] = 1
    if bias is not None:
        margin = int(weights.shape[1] * weights.shape[2]) * 127 * 127
        room = (1 << 31) - 1 - margin
        if room <= 0:
            raise OverflowError('Convolution geometry exceeds INT32 budget')
        sw = np.maximum(sw, np.abs(bias.astype(np.float64)) / (input_scale * room))
    qw = quantize(weights, sw[:, None, None])
    qb = None
    if bias is not None:
        wide = np.rint(bias.astype(np.float64) / (input_scale * sw))
        if np.any(np.abs(wide) > (1 << 31) - 1):
            raise OverflowError('Bias overflow')
        qb = wide.astype(np.int32)
    return qw, sw, qb


def residual_add(a, sa, b, sb, sy):
    """Q16 scale alignment, single nearest-even rounding after branch addition."""
    ma = int(np.rint(sa / sy * (1 << 16)))
    mb = int(np.rint(sb / sy * (1 << 16)))
    if ma < 0 or mb < 0 or max(ma, mb) > (1 << 31)-1:
        raise ValueError('Residual scale multiplier outside INT32')
    total = a.astype(np.int64)*ma + b.astype(np.int64)*mb
    return np.clip(round_shift_even(total, 16), -127, 127).astype(np.int8)


def gated(x, sx, gate, sy):
    """Host sigmoid gate in unsigned Q0.15, retained INT8 activation on FPGA."""
    if not np.all(np.isfinite(gate)) or np.any(gate < 0) or np.any(gate > 1):
        raise ValueError('SE gate must be finite in [0,1]')
    qgate = np.rint(gate.astype(np.float64) * 32768).astype(np.uint16)
    product = x.astype(np.int32) * qgate.astype(np.int32)
    return requantize(product, sx / (32768 * sy))


def evaluator(model, scales, exclude_blocks=()):
    """Execute actual ONNX masks/lengths/residual/SE ordering with integer Conv."""
    from common import block_id
    from onnx.reference.ops.op_conv import Conv as FloatConv
    from onnx.reference.ops.op_where import Where as FloatWhere
    from onnx.reference.ops.op_add import Add as FloatAdd
    from onnx.reference.ops.op_mul import Mul as FloatMul
    from onnx.reference.ops.op_relu import Relu as FloatRelu
    from onnx.reference.ops.op_reduce_sum import ReduceSum_13 as FloatReduceSum

    def boundary(op, value):
        name = op.onnx_node.output[0]
        if name not in scales or block_id(op.onnx_node.name) in exclude_blocks:
            return value
        scale = scales[name]
        return (quantize(value, scale).astype(np.float32) * np.float32(scale)).astype(np.float32)

    class Conv(OpRun):
        op_domain = ''

        def _run(self, X, W, B=None, auto_pad=None, dilations=None, group=None,
                 kernel_shape=None, pads=None, strides=None):
            if block_id(self.onnx_node.name) in exclude_blocks or self.onnx_node.name.startswith('/decoder/'):
                return FloatConv._run(self, X, W, B, auto_pad, dilations, group, kernel_shape, pads, strides)
            if auto_pad not in (None, 'NOTSET', b'NOTSET', '', b''):
                raise ValueError('Explicit padding required')
            sx = scales[self.onnx_node.input[0]]
            sy = scales[self.onnx_node.output[0]]
            qw, sw, qb = conv_parameters(W, B, sx)
            acc = conv1d(quantize(X, sx), qw, qb, (strides or [1])[0],
                         tuple(pads or [0, 0]), (dilations or [1])[0], group or 1)
            return ((requantize(acc, sx * sw / sy).astype(np.float32) * np.float32(sy)).astype(np.float32),)

    class ReduceSum(FloatReduceSum):
        op_domain = ''

        def _run(self, x, axes=None, keepdims=None, noop_with_empty_axes=None):
            name = self.onnx_node.input[0]
            if (name in scales and x.dtype == np.float32 and x.ndim == 3
                    and block_id(self.onnx_node.name) not in exclude_blocks):
                chosen = self.handle_axes(axes, noop_with_empty_axes)
                total = np.sum(quantize(x, scales[name]).astype(np.int64), axis=chosen, keepdims=keepdims)
                if np.any(total < -(1 << 31)) or np.any(total > (1 << 31)-1):
                    raise OverflowError('SE INT32 reduction overflow')
                return ((total.astype(np.float32) * np.float32(scales[name])).astype(np.float32),)
            return FloatReduceSum._run(self, x, axes, keepdims, noop_with_empty_axes)

    class Add(FloatAdd):
        op_domain = ''

        def _run(self, a, b):
            node = self.onnx_node
            if (node.output[0] in scales and all(n in scales for n in node.input)
                    and block_id(node.name) not in exclude_blocks):
                sa, sb, sy = (scales[n] for n in (*node.input, node.output[0]))
                q = residual_add(quantize(a, sa), sa, quantize(b, sb), sb, sy)
                return (q.astype(np.float32)*np.float32(sy),)
            return FloatAdd._run(self, a, b)

    class Mul(FloatMul):
        op_domain = ''

        def _run(self, a, b):
            node = self.onnx_node
            if (node.output[0] in scales and node.input[0] in scales
                    and block_id(node.name) not in exclude_blocks):
                sx, sy = scales[node.input[0]], scales[node.output[0]]
                return (gated(quantize(a, sx), sx, b, sy).astype(np.float32)*np.float32(sy),)
            return FloatMul._run(self, a, b)

    new_ops = [Conv, ReduceSum, Add, Mul]
    for base in (FloatWhere, FloatRelu):
        def wrapped(self, *args, _base=base, **kwargs):
            values = _base._run(self, *args, **kwargs)
            return (boundary(self, values[0]),)
        new_ops.append(type(base.__name__, (base,), {'op_domain': '', '_run': wrapped}))
    return ReferenceEvaluator(model, new_ops=new_ops)
