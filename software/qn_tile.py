"""Pointwise INT8 tile packet format. Board transport is supplied by caller.

No quantization, bias or activation is performed here. Arrays are [K,T] and
[O,K]; result is [O,T] INT32. Each packet computes 16 times x 16 channels.
"""
import struct
import numpy as np

MAGIC = 0x31544E51
MAX_K = 1024
OUTPUT_BYTES = 1024
MAX_BATCH_PACKETS = 128


class DMADevice:
    """Linux ioctl transport for the qn_tile kernel module (ARM64 prototype)."""
    accepts_buffer = True

    @staticmethod
    def _source(data):
        """Keep a contiguous caller buffer alive throughout the blocking ioctl."""
        import ctypes
        view = memoryview(data)
        if not view.c_contiguous:
            raise ValueError('DMA input must be C contiguous')
        view = view.cast('B')
        if view.readonly:
            source = ctypes.create_string_buffer(view.tobytes())
        else:
            source = (ctypes.c_ubyte * view.nbytes).from_buffer(view)
        return source, view.nbytes

    def __init__(self, path='/dev/qn-tile', batch_size=1):
        import os
        if not 1 <= batch_size <= MAX_BATCH_PACKETS:
            raise ValueError('Batch size must be 1..128')
        self.fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
        self.max_batch_packets = batch_size
        self.ioctl_calls = 0
        self.tile_packets = 0
        self.input_bytes_sent = 0

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
        source, size = self._source(data)
        if not 48 <= size <= 32784:
            raise ValueError('Invalid packet byte length')
        result = ctypes.create_string_buffer(OUTPUT_BYTES)
        request = struct.pack('=QQII', ctypes.addressof(source),
                              ctypes.addressof(result), size, 0)
        # Linux asm-generic _IOW('Q',1,24-byte qn_tile_request), ARM64 ABI.
        fcntl.ioctl(self.fd, 0x40185101, request)
        self.ioctl_calls += 1
        self.tile_packets += 1
        self.input_bytes_sent += size
        return result.raw

    def batch(self, data, packet_bytes):
        """Uniform QNT1 packets -> concatenated 1024-byte responses.

        nr2 ABI: u64 input/output pointers, u32 packet_bytes, u32 count.
        Each SG descriptor preserves one packet's TLAST. Batch mode requires
        the nr2 driver; errors propagate without automatic replay/fallback.
        """
        import ctypes
        import fcntl
        if self.fd is None:
            raise ValueError('DMA device is closed')
        source, size = self._source(data)
        if not 48 <= packet_bytes <= 32784 or size % packet_bytes:
            raise ValueError('Invalid uniform batch packet size')
        count = size // packet_bytes
        if not 1 <= count <= self.max_batch_packets:
            raise ValueError('Invalid batch packet count')
        if self.max_batch_packets > 1:
            result = ctypes.create_string_buffer(count * OUTPUT_BYTES)
            request = struct.pack('=QQII', ctypes.addressof(source),
                                  ctypes.addressof(result), packet_bytes, count)
            fcntl.ioctl(self.fd, 0x40185102, request)
            self.ioctl_calls += 1
            self.tile_packets += count
            self.input_bytes_sent += size
            return result.raw
        view = memoryview(data).cast('B')
        return b''.join(self(view[i*packet_bytes:(i+1)*packet_bytes]) for i in range(count))


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
    batch = getattr(transact, 'batch', None)
    limit = getattr(transact, 'max_batch_packets', 1)
    if callable(batch) and limit > 1:
        return _pointwise_batch(inputs, weights, transact, min(limit, MAX_BATCH_PACKETS))
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


def _pointwise_batch(inputs, weights, transact, limit):
    """Vectorized padded packing, uniform K per batch, exact INT32 K sums."""
    k, times = inputs.shape
    outputs = weights.shape[0]
    nt, no = (times+15)//16, (outputs+15)//16
    result = np.zeros((no*16, nt*16), dtype=np.int32)
    blocks = result.reshape(no,16,nt,16).transpose(2,0,1,3)
    for start in range(0,k,MAX_K):
        end = min(k,start+MAX_K)
        nk = end-start
        x = np.zeros((nk,nt*16), dtype=np.int8)
        w = np.zeros((nk,no*16), dtype=np.int8)
        x[:,:times] = inputs[start:end]
        w[:,:outputs] = weights[:,start:end].T
        # Reorder each tensor once; repeated gathers then read adjacent bytes.
        x_tiles = np.ascontiguousarray(x.reshape(nk,nt,16).transpose(1,0,2))
        w_tiles = np.ascontiguousarray(w.reshape(nk,no,16).transpose(1,0,2))
        header = np.frombuffer(struct.pack('<IIII',MAGIC,nk,0,0),dtype=np.uint8)
        packet_bytes = 16+32*nk
        capacity = min(limit,nt*no)
        # A blocking transaction consumes the buffer before it is reused.
        # Most model channel counts divide 128, so output-channel weights
        # repeat unchanged across successive batches of time positions.
        storage = np.empty((capacity,packet_bytes),dtype=np.uint8)
        storage[:,:16] = header
        storage_rows = storage[:,16:].view(np.int8).reshape(capacity,2,nk,16)
        weight_offset = None
        for first in range(0,nt*no,limit):
            indices = np.arange(first,min(first+limit,nt*no))
            ti, oi = indices//no, indices%no
            data = storage[:len(indices)]
            rows = storage_rows[:len(indices)]
            rows[:,0] = x_tiles[ti]
            offset = first % no
            if weight_offset != offset:
                storage_rows[:,1] = w_tiles[(np.arange(capacity)+offset)%no]
                weight_offset = offset
            payload = memoryview(data).cast('B') if getattr(transact, 'accepts_buffer', False) else data.tobytes()
            response = transact.batch(payload,packet_bytes)
            if len(response) != len(indices)*OUTPUT_BYTES:
                raise ValueError('Incomplete batch response')
            sums = np.frombuffer(response,dtype='<i4').reshape(len(indices),16,16).transpose(0,2,1)
            blocks[ti,oi] += sums
    return result[:outputs,:times].copy()
