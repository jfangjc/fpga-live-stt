#!/usr/bin/env python3
"""Experimental full-model dynamic INT8 pointwise / FP32 CPU hybrid.

CPU emulation is not hardware execution. No calibration corpus or WER validation.
Run DMA mode only after the standalone V2 tile board test passes.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

import numpy as np
import onnx
from onnx import numpy_helper, helper

from quartznet_cpu import read_pcm24, frontend, decode
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qn_tile import DMADevice, pointwise


def quantize(values, scale):
    return np.clip(np.rint(values / scale), -127, 127).astype(np.int8)


def conv_windows(x, w, attrs):
    if x.ndim != 3 or w.ndim != 3:
        raise ValueError('Only NCT 1D Conv is supported')
    if attrs.get('auto_pad', b'NOTSET') not in (b'NOTSET', b''):
        raise ValueError('Unsupported Conv auto_pad')
    stride, = attrs.get('strides', [1])
    dilation, = attrs.get('dilations', [1])
    left, right = attrs.get('pads', [0, 0])
    group = attrs.get('group', 1)
    if stride < 1 or dilation < 1 or min(left, right) < 0:
        raise ValueError('Invalid Conv attributes')
    if x.shape[1] % group or w.shape[0] % group or w.shape[1] != x.shape[1] // group:
        raise ValueError('Invalid grouped Conv shape')
    if attrs.get('kernel_shape', list(w.shape[2:])) != list(w.shape[2:]):
        raise ValueError('Conv kernel shape mismatch')
    padded = np.pad(x, ((0, 0), (0, 0), (left, right)))
    extent = dilation * (w.shape[2] - 1) + 1
    windows = np.lib.stride_tricks.sliding_window_view(padded, extent, axis=2)
    return windows[:, :, ::stride, ::dilation], group


class Graph:
    def __init__(self, path, mode='fp32', transact=None, cpu_conv_backend='numpy', cpu_conv_threads=4):
        if mode not in ('fp32', 'emulate', 'dma') or (mode == 'dma' and transact is None):
            raise ValueError('Invalid graph execution mode')
        model = onnx.load(str(path))
        onnx.checker.check_model(model)
        if [(o.domain, o.version) for o in model.opset_import] != [('', 17)]:
            raise ValueError('Only default-domain ONNX opset 17 is supported')
        if [i.name for i in model.graph.input] != ['audio_signal'] or [o.name for o in model.graph.output] != ['logprobs']:
            raise ValueError('Unexpected graph I/O')
        self.weights = {i.name: numpy_helper.to_array(i).astype(np.float32) for i in model.graph.initializer}
        self.nodes = list(model.graph.node)
        self.attrs = {n.name: {a.name: helper.get_attribute_value(a) for a in n.attribute} for n in self.nodes}
        if len(self.attrs) != len(self.nodes):
            raise ValueError('Node names must be unique')
        self.quantized = {}
        self.uses = Counter(name for n in self.nodes for name in n.input)
        self.mode, self.transact = mode, transact
        self.stats = []
        if cpu_conv_backend not in ('numpy', 'ort', 'native'):
            raise ValueError('Unsupported CPU Conv backend')
        self.cpu_conv_backend = cpu_conv_backend
        self.cpu_sessions = {}
        self.native = None
        self.native_nodes = set()
        for node in self.nodes:
            if node.domain or node.op_type not in ('Conv', 'Relu', 'Add', 'Transpose', 'LogSoftmax') or len(node.output) != 1:
                raise ValueError(f'Unsupported node: {node.name} {node.domain}:{node.op_type}')
            if node.op_type == 'Conv':
                if node.input[1] not in self.weights or (len(node.input) > 2 and node.input[2] not in self.weights):
                    raise ValueError('Only constant Conv weights/bias are supported')
                w = self.weights[node.input[1]]
                if w.ndim != 3:
                    raise ValueError('Only 1D convolutions are supported')
                if self.attrs[node.name].get('group', 1) == 1 and w.shape[2] == 1:
                    scales = np.max(np.abs(w[:, :, 0]), axis=1).astype(np.float32) / np.float32(127)
                    scales[scales == 0] = 1
                    self.quantized[node.name] = (quantize(w[:, :, 0], scales[:, None]), scales)

        if cpu_conv_backend == 'native':
            from native_depthwise import NativeDepthwise
            self.native = NativeDepthwise(threads=cpu_conv_threads)
            for node in self.nodes:
                if node.op_type != 'Conv' or (mode != 'fp32' and node.name in self.quantized):
                    continue
                w = self.weights[node.input[1]]
                attrs = self.attrs[node.name]
                if w.shape[1] == 1 and attrs.get('group',1) == w.shape[0] and attrs.get('auto_pad',b'NOTSET') in (b'NOTSET',b''):
                    self.native_nodes.add(node.name)

        if cpu_conv_backend == 'ort':
            import onnxruntime as ort
            options = ort.SessionOptions()
            # Avoid one thread pool per Conv; these kernels run sequentially.
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            # Do not retain an arena/workspace cache for each separate node.
            options.enable_cpu_mem_arena = False
            options.enable_mem_pattern = False
            for node in self.nodes:
                if node.op_type != 'Conv' or (mode != 'fp32' and node.name in self.quantized):
                    continue
                w = self.weights[node.input[1]]
                group = self.attrs[node.name].get('group', 1)
                graph = helper.make_graph(
                    [node], node.name,
                    [helper.make_tensor_value_info(node.input[0], onnx.TensorProto.FLOAT,
                                                   ['N', w.shape[1]*group, 'T'])],
                    [helper.make_tensor_value_info(node.output[0], onnx.TensorProto.FLOAT,
                                                   ['N', w.shape[0], 'T_out'])],
                    [numpy_helper.from_array(self.weights[name], name)
                     for name in node.input[1:]])
                conv_model = helper.make_model(graph, opset_imports=list(model.opset_import))
                conv_model.ir_version = model.ir_version
                onnx.checker.check_model(conv_model)
                self.cpu_sessions[node.name] = ort.InferenceSession(
                    conv_model.SerializeToString(), options,
                    providers=['CPUExecutionProvider'])

    def convolution(self, node, x):
        if node.name in self.native_nodes:
            bias = self.weights[node.input[2]] if len(node.input) > 2 else None
            return self.native(x,self.weights[node.input[1]],bias,self.attrs[node.name])
        if node.name in self.cpu_sessions:
            return self.cpu_sessions[node.name].run(
                None, {node.input[0]: np.ascontiguousarray(x)})[0]
        w = self.weights[node.input[1]]
        windows, group = conv_windows(x, w, self.attrs[node.name])
        if self.mode != 'fp32' and node.name in self.quantized:
            # Whole-layer activation scale, shared across N/C/T. Bias stays FP32.
            act_scale = np.float32(np.max(np.abs(x)) / np.float32(127))
            if act_scale == 0:
                act_scale = np.float32(1)
            if not np.isfinite(act_scale):
                raise ValueError('Non-finite activation quantization scale')
            qw, weight_scale = self.quantized[node.name]
            qx = quantize(windows[..., 0], act_scale)
            out = []
            for batch in qx:
                if self.mode == 'dma':
                    sums = pointwise(batch, qw, self.transact)
                else:
                    # Batched exact INT32 CPU matmul, not a hardware timing model.
                    if batch.shape[0] * 16384 > np.iinfo(np.int32).max:
                        raise ValueError('Unsafe INT32 reduction length')
                    sums = qw.astype(np.int32) @ batch.astype(np.int32)
                out.append(sums.astype(np.float32) * (weight_scale * act_scale)[:, None])
            y = np.stack(out)
        elif group == x.shape[1] and w.shape[1] == 1:
            multiplier = w.shape[0] // group
            y = np.einsum('nctk,cmk->ncmt', windows,
                          w.reshape(group, multiplier, w.shape[2]), optimize=False,
                          dtype=np.float32).reshape(x.shape[0], w.shape[0], windows.shape[2])
        elif group == 1 and w.shape[2] == 1:
            y = np.matmul(w[:, :, 0], windows[..., 0])
        else:
            # General grouped 1D convolution, preserving channel grouping.
            cin, cout = x.shape[1] // group, w.shape[0] // group
            parts = [np.einsum('nctk,ock->not', windows[:, g*cin:(g+1)*cin],
                              w[g*cout:(g+1)*cout], optimize=False, dtype=np.float32)
                     for g in range(group)]
            y = np.concatenate(parts, axis=1)
        if len(node.input) > 2:
            y = y + self.weights[node.input[2]][None, :, None]
        return y.astype(np.float32, copy=False)

    def run(self, features, observer=None):
        if features.dtype != np.float32 or features.ndim != 3 or features.shape[1] != 64:
            raise ValueError('Expected FP32 features [N,64,T]')
        values = dict(self.weights)
        values['audio_signal'] = features
        uses = self.uses.copy()
        self.stats = []
        for node in self.nodes:
            start = time.perf_counter()
            dma_calls_before = getattr(self.transact, 'ioctl_calls', 0)
            dma_bytes_before = getattr(self.transact, 'input_bytes_sent', 0)
            args = [values[name] for name in node.input]
            attrs = self.attrs[node.name]
            if node.op_type == 'Conv':
                y = self.convolution(node, args[0])
            elif node.op_type == 'Relu':
                y = np.maximum(args[0], np.float32(0))
            elif node.op_type == 'Add':
                y = args[0] + args[1]
            elif node.op_type == 'Transpose':
                y = args[0].transpose(attrs.get('perm', list(reversed(range(args[0].ndim)))))
            else:
                axis = attrs.get('axis', -1)
                shifted = args[0] - np.max(args[0], axis=axis, keepdims=True)
                y = shifted - np.log(np.sum(np.exp(shifted), axis=axis, keepdims=True))
            if not np.all(np.isfinite(y)):
                raise ValueError(f'Non-finite result at {node.name}')
            quantized = self.mode != 'fp32' and node.name in self.quantized
            record = {'name': node.name, 'op': node.op_type, 'seconds': time.perf_counter()-start,
                      'shape': list(y.shape), 'int8_pointwise': quantized}
            if quantized:
                record['tile_transactions'] = int(y.shape[0] * ((y.shape[2]+15)//16) *
                                                   ((y.shape[1]+15)//16) * ((args[0].shape[1]+1023)//1024))
                if self.mode == 'dma':
                    record['dma_ioctl_calls'] = self.transact.ioctl_calls-dma_calls_before
                    record['dma_input_bytes'] = self.transact.input_bytes_sent-dma_bytes_before
            self.stats.append(record)
            values[node.output[0]] = y
            if observer:
                observer(node, y)
            for name in node.input:
                uses[name] -= 1
                if uses[name] == 0 and name not in self.weights:
                    del values[name]
        return values['logprobs']


def vocabulary(directory):
    result = {}
    for line in (directory / 'vocab.txt').read_text(encoding='utf-8').splitlines():
        token, index = line.rsplit(' ', 1)
        result[int(index)] = token
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wav', type=Path)
    parser.add_argument('--model', type=Path, default=Path(__file__).parent / 'model')
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--emulate-tile', action='store_true')
    modes.add_argument('--fp32-numpy', action='store_true')
    modes.add_argument('--device', help='DMA device; only after V2 board tile validation')
    parser.add_argument('--dma-batch-size', type=int, default=1,
                        help='DMA packets per ioctl (1..128); >1 requires batch driver, default 1')
    parser.add_argument('--remove-dc', action='store_true')
    parser.add_argument('--cpu-conv-backend', choices=('numpy', 'ort', 'native'), default='numpy',
                        help='CPU Conv implementation; INT8 pointwise still uses selected transport')
    parser.add_argument('--cpu-conv-threads',type=int,choices=range(1,5),default=4,
                        help='Threads for optional native depthwise CPU Conv (1..4)')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if not 1 <= args.dma_batch_size <= 128:
        parser.error('--dma-batch-size must be 1..128')
    audio = read_pcm24(args.wav)
    if args.remove_dc:
        audio -= audio.mean()
    mode = 'dma' if args.device else 'fp32' if args.fp32_numpy else 'emulate'
    transport = DMADevice(args.device, batch_size=args.dma_batch_size) if args.device else None
    try:
        graph_setup_started = time.perf_counter()
        graph = Graph(args.model / 'model.onnx', mode, transport, args.cpu_conv_backend, args.cpu_conv_threads)
        graph_setup_seconds = time.perf_counter()-graph_setup_started
        start = time.perf_counter()
        features, valid = frontend(audio)
        prepared = time.perf_counter()
        output = graph.run(features[:, :, :valid].copy())
        inferred = time.perf_counter()
        text = decode(output, vocabulary(args.model), (valid + 1)//2)
        ended = time.perf_counter()
        report = {'experimental': True, 'accuracy_validated': False, 'calibration_corpus': None,
                  'mode': mode, 'hardware_execution': mode == 'dma', 'transcript': text,
                  'audio_seconds': len(audio)/16000, 'remove_dc': args.remove_dc,
                  'frontend_seconds': prepared-start, 'inference_seconds': inferred-prepared,
                  'decode_seconds': ended-inferred, 'total_seconds': ended-start,
                  'real_time_factor': (ended-start)/(len(audio)/16000),
                  'tile_transactions': sum(n.get('tile_transactions', 0) for n in graph.stats),
                  'dma_batch_size': args.dma_batch_size if transport else None,
                  'ioctl_calls': transport.ioctl_calls if transport else 0,
                  'tile_packets': transport.tile_packets if transport else 0,
                  'dma_input_bytes': transport.input_bytes_sent if transport else 0,
                  'cpu_conv_backend': args.cpu_conv_backend,
                  'cpu_conv_threads': graph.native.threads if graph.native else 1 if args.cpu_conv_backend == 'ort' else None,
                  'native_cpu_conv_nodes':len(graph.native_nodes),
                  'native_cpu_conv_calls':graph.native.calls if graph.native else 0,
                  'native_library_sha256':graph.native.sha256 if graph.native else None,
                  'graph_setup_seconds': graph_setup_seconds,
                  'layers': graph.stats}
        if args.report:
            args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k != 'layers'}, indent=2))
    finally:
        if transport:
            transport.close()


if __name__ == '__main__':
    main()
