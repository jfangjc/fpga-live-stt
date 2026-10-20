"""Cached signed INT8 pointwise protocol; no quantization or FP32 math.

LOAD replaces the complete layer weight cache. RUN reuses it for 16 time
positions and computes every output channel. This transport requires the
matching cached RTL and driver; legacy tile hardware is not a fallback.
"""
import struct
import numpy as np

MAGIC = 0x32434E51  # QNC2
LOAD = 1
RUN = 2
INVALIDATE = 3
RESPONSE_MAGIC = 0x32524E51
MAX_K = 1024
MAX_M = 1024
MAX_BATCH_PACKETS = 128
MAX_BATCH_RX_BYTES = 133120


def _weights(weights):
    weights = np.asarray(weights)
    if weights.dtype != np.int8:
        raise TypeError('Weights must be quantized signed INT8')
    if weights.ndim != 2 or not 1 <= weights.shape[0] <= MAX_M or not 1 <= weights.shape[1] <= MAX_K:
        raise ValueError('Expected W[M,K], with M and K in 1..1024')
    return weights


def header(opcode, k, m, tag):
    if not 1 <= tag <= 0xffffffff:
        raise ValueError('Cache tag must be nonzero uint32')
    return struct.pack('<IIII',MAGIC,opcode | (m<<16),k,tag)


def load_packet(weights, tag=1):
    weights = _weights(weights)
    m, k = weights.shape
    blocks = (m+15)//16
    padded = np.zeros((blocks*16,k),dtype=np.int8)
    padded[:m] = weights
    payload = np.ascontiguousarray(padded.reshape(blocks,16,k).transpose(0,2,1))
    return header(LOAD,k,m,tag) + payload.tobytes()


def run_packet(inputs, outputs, tag=1):
    inputs = np.asarray(inputs)
    if inputs.dtype != np.int8:
        raise TypeError('Inputs must be quantized signed INT8')
    if inputs.ndim != 2 or not 1 <= inputs.shape[0] <= MAX_K or not 1 <= inputs.shape[1] <= 16 or not 1 <= outputs <= MAX_M:
        raise ValueError('Expected X[K,T], K 1..1024, T 1..16 and M 1..1024')
    k,t = inputs.shape
    padded = np.zeros((k,16),dtype=np.int8)
    padded[:,:t] = inputs
    return header(RUN,k,outputs,tag) + padded.tobytes()


def output_bytes(outputs):
    if not 1 <= outputs <= MAX_M:
        raise ValueError('M must be 1..1024')
    return 16+((outputs+15)//16)*1024


def validate_response(response,k,m,tag):
    if len(response) < 16:
        raise ValueError('Incomplete cached acknowledgement')
    magic,status,dims,actual_tag = struct.unpack('<IIII',response[:16])
    if magic != RESPONSE_MAGIC or dims != (k | (m<<16)) or actual_tag != tag:
        raise ValueError('Cached acknowledgement identity mismatch')
    if status:
        raise RuntimeError(f'Cached accelerator status {status}')


def unpack(response, outputs, times=16, *, k, tag):
    if len(response) != output_bytes(outputs) or not 1 <= times <= 16:
        raise ValueError('Incomplete cached response or invalid time count')
    blocks = (outputs+15)//16
    validate_response(response,k,outputs,tag)
    return np.frombuffer(response,offset=16,dtype='<i4').reshape(blocks,16,16).transpose(0,2,1).reshape(blocks*16,16)[:outputs,:times].copy()


class CachedDMADevice:
    """Matching nr3/nr4 Linux DMA transport; exceptions never replay commands."""
    def __init__(self,path='/dev/qn-tile',cached_batch_size=128):
        import os
        if not 1 <= cached_batch_size <= MAX_BATCH_PACKETS:
            raise ValueError('Cached batch size must be 1..128')
        self.fd = os.open(path,os.O_RDWR | os.O_CLOEXEC)
        self.max_batch_packets = cached_batch_size
        self.ioctl_calls = self.tile_packets = self.input_bytes_sent = self.output_bytes_received = 0
        self.load_commands = self.run_commands = self.invalidate_commands = 0
        self.tag = 0
        self.loaded = None

    def __enter__(self):
        return self

    def __exit__(self,*_):
        self.close()

    def close(self):
        import os
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.loaded = None

    def transaction(self,data,response_bytes):
        import ctypes
        import fcntl
        from qn_tile import DMADevice
        if self.fd is None:
            raise ValueError('Cached DMA device is closed')
        source,size = DMADevice._source(data)
        result = ctypes.create_string_buffer(response_bytes)
        request = struct.pack('=QQIIII',ctypes.addressof(source),ctypes.addressof(result),size,response_bytes,0,0)
        try:
            fcntl.ioctl(self.fd,0xc0205103,request)
        except BaseException:
            self.loaded = None
            raise
        self.ioctl_calls += 1
        self.input_bytes_sent += size
        self.output_bytes_received += response_bytes
        return result.raw

    def batch_transaction(self,data,packet_bytes,response_bytes,count):
        import ctypes
        import fcntl
        from qn_tile import DMADevice
        if self.fd is None:
            raise ValueError('Cached DMA device is closed')
        source,size = DMADevice._source(data)
        if not 1 <= count <= min(self.max_batch_packets,MAX_BATCH_PACKETS) or \
           not 32 <= packet_bytes <= 16400 or packet_bytes % 16 or \
           not 1040 <= response_bytes <= 65552 or (response_bytes-16) % 1024 or \
           size != packet_bytes*count or response_bytes*count > MAX_BATCH_RX_BYTES:
            raise ValueError('Invalid cached RUN batch dimensions/buffer sizes')
        result = ctypes.create_string_buffer(response_bytes*count)
        request = struct.pack('=QQIIII',ctypes.addressof(source),ctypes.addressof(result),
                              packet_bytes,response_bytes,count,0)
        try:
            fcntl.ioctl(self.fd,0xc0205104,request)
        except BaseException:
            self.loaded = None
            raise
        self.ioctl_calls += 1
        self.input_bytes_sent += size
        self.output_bytes_received += response_bytes*count
        return result.raw

    def load(self,weights):
        weights = _weights(weights)
        m,k = weights.shape
        self.loaded = None
        self.tag = (self.tag % 0xffffffff)+1
        response = self.transaction(load_packet(weights,self.tag),16)
        validate_response(response,k,m,self.tag)
        self.loaded = (k,m,self.tag)
        self.load_commands += 1

    def run(self,inputs,outputs):
        inputs = np.asarray(inputs)
        if self.loaded is None or inputs.ndim != 2 or self.loaded[:2] != (inputs.shape[0],outputs):
            raise ValueError('RUN requires matching successfully loaded layer')
        k,m,tag = self.loaded
        response = self.transaction(run_packet(inputs,m,tag),output_bytes(m))
        try:
            result = unpack(response,m,inputs.shape[1],k=k,tag=tag)
        except BaseException:
            self.loaded = None
            raise
        self.run_commands += 1
        self.tile_packets += (m+15)//16
        return result

    def run_many(self,inputs,outputs):
        """Return X[K,T] layer sums using bounded homogeneous RUN batches."""
        inputs = np.asarray(inputs)
        if inputs.dtype != np.int8:
            raise TypeError('Inputs must be quantized signed INT8')
        if self.loaded is None or inputs.ndim != 2 or inputs.shape[1] < 1 or self.loaded[:2] != (inputs.shape[0],outputs):
            raise ValueError('RUN batch requires nonempty inputs and matching loaded layer')
        k,m,tag = self.loaded
        times = inputs.shape[1]
        packet_bytes,response_bytes = 16+16*k,output_bytes(m)
        limit = min(self.max_batch_packets,MAX_BATCH_PACKETS,MAX_BATCH_RX_BYTES//response_bytes)
        result = np.empty((m,times),dtype=np.int32)
        for start in range(0,times,limit*16):
            end = min(start+limit*16,times)
            count = (end-start+15)//16
            padded = np.zeros((k,count*16),dtype=np.int8)
            padded[:,:end-start] = inputs[:,start:end]
            storage = np.empty((count,packet_bytes),dtype=np.uint8)
            storage[:,:16] = np.frombuffer(header(RUN,k,m,tag),dtype=np.uint8)
            storage[:,16:].view(np.int8).reshape(count,k,16)[:] = padded.reshape(k,count,16).transpose(1,0,2)
            response = self.batch_transaction(memoryview(storage).cast('B'),packet_bytes,response_bytes,count)
            try:
                if len(response) != count*response_bytes:
                    raise ValueError('Incomplete cached batch response')
                for index in range(count):
                    offset = start+index*16
                    nt = min(16,times-offset)
                    result[:,offset:offset+nt] = unpack(response[index*response_bytes:(index+1)*response_bytes],m,nt,k=k,tag=tag)
            except BaseException:
                self.loaded = None
                raise
            self.run_commands += count
            self.tile_packets += count*((m+15)//16)
        return result

    def invalidate(self):
        self.loaded = None
        response = self.transaction(struct.pack('<IIII',MAGIC,INVALIDATE,0,0),16)
        validate_response(response,0,0,0)
        self.invalidate_commands += 1


def pointwise(inputs, weights, transport):
    inputs, weights = np.asarray(inputs), _weights(weights)
    if inputs.dtype != np.int8:
        raise TypeError('Inputs must be quantized signed INT8')
    if inputs.ndim != 2 or inputs.shape[0] != weights.shape[1] or inputs.shape[1] < 1:
        raise ValueError('Expected nonempty X[K,T] and matching W[M,K]')
    outputs,times = weights.shape[0],inputs.shape[1]
    # Always reload each layer. Cache identities must not rely on host object
    # addresses, which can be recycled or mutated between graph invocations.
    transport.load(weights)
    return transport.run_many(inputs,outputs)
