"""Check Linux ABI buffer lifetime/pointers and compare host packet packing."""
import ctypes
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import struct
import sys
import time
import types
import numpy as np

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--before',default='reports/qn_tile_before_packing.py')
parser.add_argument('--report',default='reports/dma_packing_host.json')
options = parser.parse_args()
sys.path.insert(0, str(root/'software'))
import qn_tile

calls = []
expected_pointer = None
expected_data = None
def ioctl(fd, command, request):
    src, dst, size, count = struct.unpack('=QQII', request)
    count = count if command == 0x40185102 else 1
    assert fd == 42 and command in (0x40185101, 0x40185102)
    if expected_pointer is not None:
        assert src == expected_pointer, 'Writable input was copied'
    assert ctypes.string_at(src, size*count) == expected_data
    response = np.arange(count*256, dtype='<i4').tobytes()
    ctypes.memmove(dst, response, len(response))
    calls.append(command)
    return 0

saved = sys.modules.get('fcntl')
sys.modules['fcntl'] = types.SimpleNamespace(ioctl=ioctl)
try:
    device = qn_tile.DMADevice.__new__(qn_tile.DMADevice)
    device.fd = 42
    device.max_batch_packets = 128
    device.ioctl_calls = device.tile_packets = device.input_bytes_sent = 0
    raw = np.arange(96, dtype=np.uint8)
    for data in (raw, memoryview(raw), bytearray(raw), raw.tobytes()):
        expected_data = bytes(data)
        expected_pointer = None if memoryview(data).readonly else ctypes.addressof(
            ctypes.c_ubyte.from_buffer(data))
        result = device.batch(data, 48)
        np.testing.assert_array_equal(np.frombuffer(result, '<i4'), np.arange(512))
    device.max_batch_packets = 1
    expected_data = bytes(raw[:48])
    expected_pointer = raw.ctypes.data
    np.testing.assert_array_equal(np.frombuffer(device.batch(raw[:48],48),'<i4'),np.arange(256))
    for data in (raw[::2], np.zeros(47, np.uint8)):
        try:
            device.batch(data,48)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid buffer accepted')
finally:
    if saved is None:
        del sys.modules['fcntl']
    else:
        sys.modules['fcntl'] = saved

spec = importlib.util.spec_from_file_location('old_tile',root/options.before)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
class Sink:
    max_batch_packets = 128
    accepts_buffer = True
    def __init__(self):
        self.digest = hashlib.sha256()
        self.packets = 0
    def batch(self,data,packet_bytes):
        self.digest.update(data)
        count = len(data)//packet_bytes
        self.packets += count
        return bytes(count*1024)

rng = np.random.default_rng(8439)
benchmarks = []
for k,t,o in ((512,500,512),(512,500,1024),(1025,35,49),(17,113,35),(17,35,2081)):
    x = rng.integers(-128,128,(k,t),dtype=np.int8)
    w = rng.integers(-128,128,(o,k),dtype=np.int8)
    timings = [[],[]]
    digests = []
    for iteration in range(4):
        for index,module in enumerate((old,qn_tile)):
            sink = Sink()
            started = time.perf_counter()
            result = module.pointwise(x,w,sink)
            timings[index].append(time.perf_counter()-started)
            assert not result.any()
            digests.append(sink.digest.hexdigest())
    assert len(set(digests)) == 1, 'Wire packet sequence changed'
    benchmarks.append({'k':k,'times':t,'outputs':o,
                       'before_seconds':statistics.median(timings[0]),
                       'after_seconds':statistics.median(timings[1]),
                       'wire_packets_identical':True})
report = {'result':'PASS','hardware_execution':False,
          'writable_inputs_passed_without_copy':True,'abi_checks':len(calls),
          'packing_benchmarks':benchmarks,
          'note':'Host packing only, SHA hashing/zero responses; no FPGA or ARM throughput claim'}
(root/options.report).write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
