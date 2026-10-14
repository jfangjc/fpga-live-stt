import unittest
import numpy as np
import onnx
from onnx import helper, numpy_helper
from oracle import conv1d, quantize, round_shift_even, requantize, evaluator, conv_parameters, residual_add, gated
from common import session, expose, blocks
from experiment import qdq_model


class Arithmetic(unittest.TestCase):
    def test_grouped_strided_dilated_against_scalar(self):
        rng = np.random.default_rng(97)
        for group, channels, outputs in ((1, 3, 4), (2, 4, 6), (4, 4, 4)):
            x = rng.integers(-127, 128, (2, channels, 11), dtype=np.int8)
            w = rng.integers(-127, 128, (outputs, channels//group, 3), dtype=np.int8)
            bias = rng.integers(-2000, 2000, outputs, dtype=np.int32)
            actual = conv1d(x, w, bias, stride=2, pads=(2, 1), dilation=2, group=group)
            expected = np.zeros_like(actual)
            for n in range(2):
                for o in range(outputs):
                    g = o // (outputs//group)
                    for t in range(actual.shape[-1]):
                        total = int(bias[o])
                        for c in range(channels//group):
                            for k in range(3):
                                at = t*2-2+k*2
                                if 0 <= at < 11:
                                    total += int(x[n, g*(channels//group)+c, at])*int(w[o, c, k])
                        expected[n, o, t] = total
            np.testing.assert_array_equal(actual, expected)

    def test_signed_ties_to_even(self):
        np.testing.assert_array_equal(round_shift_even(np.arange(-9, 10, dtype=np.int64), 1),
                                      np.rint(np.arange(-9, 10)/2).astype(np.int64))
        acc = np.array([[[-5, -3, -1, 1, 3, 5, 1000]]], dtype=np.int32)
        np.testing.assert_array_equal(requantize(acc, .5), [[[-2, -2, 0, 0, 2, 2, 127]]])
        np.testing.assert_array_equal(requantize(acc, 1e-40), np.zeros_like(acc, dtype=np.int8))

    def test_overflow_and_invalid_input_fail(self):
        with self.assertRaises(OverflowError):
            conv1d(np.array([[[127]]], np.int8), np.array([[[127]]], np.int8),
                   np.array([2147483647], np.int32))
        with self.assertRaises(ValueError):
            quantize(np.array([np.nan]), .1)
        with self.assertRaises(ValueError):
            quantize(np.array([1.]), 0)
        np.testing.assert_array_equal(quantize(np.array([-100, -.25, -.15, .15, .25, 100]), .1),
                                      [-127, -2, -1, 1, 2, 127])

    def test_near_zero_weights_nonzero_bias(self):
        qw, sw, qb = conv_parameters(np.full((1, 1, 1), 1e-35, np.float32), np.array([.3], np.float32), .01)
        self.assertEqual(int(qw[0, 0, 0]), 0)
        self.assertLess(int(qb[0]), 2147483647)
        result = requantize(conv1d(np.ones((1, 1, 1), np.int8), qw, qb), .01*sw/.01)
        np.testing.assert_array_equal(result, [[[30]]])

    def test_residual_and_gate_integer_contract(self):
        a = np.array([[[-127, -1, 0, 1, 127]]], np.int8)
        b = np.array([[[127, 1, 0, -1, -127]]], np.int8)
        np.testing.assert_array_equal(residual_add(a, .2, b, .1, .1), a)
        np.testing.assert_array_equal(gated(a, .1, np.array([[[.5]]]), .1),
                                      np.clip(np.rint(a.astype(float)*.5), -127, 127).astype(np.int8))


def fixture():
    rng = np.random.default_rng(4)
    nodes = [helper.make_node('Conv', ['x', 'dw'], ['d'], name='/encoder/encoder.2/dw',
                             group=3, pads=[1, 1]),
             helper.make_node('Conv', ['d', 'pw', 'bias'], ['p'], name='/encoder/encoder.2/pw'),
             helper.make_node('Add', ['p', 'x'], ['r'], name='/encoder/encoder.2/Add'),
             helper.make_node('Relu', ['r'], ['y'], name='/encoder/encoder.2/Relu')]
    initial = [numpy_helper.from_array(rng.normal(0, .1, (3, 1, 3)).astype(np.float32), 'dw'),
               numpy_helper.from_array(rng.normal(0, .1, (3, 3, 1)).astype(np.float32), 'pw'),
               numpy_helper.from_array(np.array([.01, -.02, .03], np.float32), 'bias')]
    graph = helper.make_graph(nodes, 'fused_fixture', [helper.make_tensor_value_info('x', 1, [1, 3, 'T'])],
                              [helper.make_tensor_value_info('y', 1, [1, 3, 'T'])], initial)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)], ir_version=9)
    return onnx.shape_inference.infer_shapes(model)


class Graph(unittest.TestCase):
    def test_integer_and_qdq_fixture_with_residual(self):
        model = fixture()
        scales = {n: .01 for n in ('x', 'd', 'p', 'r', 'y')}
        x = np.random.default_rng(11).normal(0, .3, (1, 3, 19)).astype(np.float32)
        integer = evaluator(model, scales).run(None, {'x': x})[0]
        qdq = session(qdq_model(model, scales), 1, optimize=False).run(None, {'x': x})[0]
        # Bias quantization and Q31 may differ from FP32/QDQ by a small number of output quanta.
        self.assertLessEqual(float(np.max(np.abs(integer-qdq))), .020001)
        self.assertTrue(np.all(integer >= 0))
        np.testing.assert_allclose(integer/.01, np.rint(integer/.01), atol=1e-5)

    def test_excluded_block_is_fp32(self):
        model = fixture()
        x = np.ones((1, 3, 17), np.float32)
        reference = session(model, 1, optimize=False).run(None, {'x': x})[0]
        actual = evaluator(model, {}, [2]).run(None, {'x': x})[0]
        np.testing.assert_allclose(actual, reference, atol=1e-6)

    def test_graph_boundaries_and_exposure(self):
        model = fixture()
        self.assertEqual(blocks(model)[0]['inputs'], ['x'])
        self.assertEqual(blocks(model)[0]['outputs'], ['y'])
        expanded = expose(model, ['d', 'p'])
        self.assertEqual([o.name for o in expanded.graph.output], ['y', 'd', 'p'])
        onnx.checker.check_model(expanded)


if __name__ == '__main__':
    unittest.main()
