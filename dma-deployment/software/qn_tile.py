"""Pointwise INT8 tile packet format. Board transport is supplied by caller.

No quantization, bias or activation is performed here. Arrays are [K,T] and
[O,K]; result is [O,T] INT32. Each packet computes 16 times x 16 channels.
"""
import struct
import numpy as np

MAGIC = 0x31544E51
MAX_K = 1024
OUTPUT_BYTES = 1024


class DMADevice:
    """Linux ioctl transport for the qn_tile kernel module (ARM64 prototype)."""
    def __init__(self, path='/dev/qn-tile'):
        import os
        self.fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        import os
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __call__(self, data):
        import ctypes
        import fcntl
        if self.fd is None:
            raise ValueError('DMA device is closed')
        if not 48 <= len(data) <= 32784:
            raise ValueError('Invalid packet byte length')
        source = ctypes.create_string_buffer(data)
        result = ctypes.create_string_buffer(OUTPUT_BYTES)
        request = struct.pack('=QQII', ctypes.addressof(source),
                              ctypes.addressof(result), len(data), 0)
        # Linux asm-generic _IOW('Q',1,24-byte qn_tile_request), ARM64 ABI.
        fcntl.ioctl(self.fd, 0x40185101, request)
        return result.raw


def packet(inputs, weights):
    inputs, weights = np.asarray(inputs), np.asarray(weights)
    if inputs.dtype != np.int8 or weights.dtype != np.int8:
        raise TypeError("Inputs and weights must already be quantized signed INT8")
    if inputs.ndim != 2 or weights.ndim != 2:
        raise ValueError("Expected X[K,T] and W[O,K]")
    k, times = inputs.shape
    outputs, wk = weights.shape
    if not 1 <= k <= MAX_K or wk != k or not 1 <= times <= 16 or not 1 <= outputs <= 16:
        raise ValueError("Packet requires K 1..1024 and T/O 1..16 with matching K")
    x = np.zeros((k, 16), dtype=np.int8)
    w = np.zeros((k, 16), dtype=np.int8)
    x[:, :times] = inputs
    w[:, :outputs] = weights.T
    return struct.pack('<IIII', MAGIC, k, 0, 0) + x.tobytes() + w.tobytes()


def unpack(response, outputs=16, times=16):
    if len(response) != OUTPUT_BYTES or not 1 <= outputs <= 16 or not 1 <= times <= 16:
        raise ValueError("Invalid result size or lane count")
    return np.frombuffer(response, dtype='<i4').reshape(16, 16)[:times, :outputs].T.copy()


def pointwise(inputs, weights, transact):
    """Compute a complete layer via transact(packet)->1024 response bytes.

    Hardware transport MUST raise on tile error, DMA timeout or incomplete
    result. Current implementation issues one transaction per spatial tile;
    throughput must be measured before using it for full-model inference.
    """
    inputs, weights = np.asarray(inputs), np.asarray(weights)
    if inputs.dtype != np.int8 or weights.dtype != np.int8:
        raise TypeError("Expected quantized INT8 tensors")
    if inputs.ndim != 2 or weights.ndim != 2 or inputs.shape[0] != weights.shape[1]:
        raise ValueError("Expected X[K,T], W[O,K] with matching K")
    k, times = inputs.shape
    outputs = weights.shape[0]
    if k < 1 or times < 1 or outputs < 1:
        raise ValueError("Empty tensors are unsupported")
    # Exact worst-case signed INT8 bound for INT32 accumulation.
    if k * 16384 > np.iinfo(np.int32).max:
        raise ValueError("K exceeds safe INT32 accumulation bound")
    result = np.zeros((outputs, times), dtype=np.int32)
    for t in range(0, times, 16):
        nt = min(16, times-t)
        for o in range(0, outputs, 16):
            no = min(16, outputs-o)
            for start in range(0, k, MAX_K):
                end = min(k, start+MAX_K)
                response = transact(packet(inputs[start:end, t:t+nt], weights[o:o+no, start:end]))
                result[o:o+no, t:t+nt] += unpack(response, no, nt)
    return result
