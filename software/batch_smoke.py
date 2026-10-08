#!/usr/bin/env python3
"""Exact batch transport checks and timings; --emulate never accesses hardware."""
import argparse
import json
from pathlib import Path
import struct
import time

import numpy as np
from qn_tile import DMADevice, MAGIC, MAX_BATCH_PACKETS, OUTPUT_BYTES, packet, pointwise


class EmulatedBatch:
    def __init__(self, batch_size=128):
        self.max_batch_packets = batch_size
        self.ioctl_calls = self.tile_packets = self.input_bytes_sent = 0

    def __call__(self, data):
        return self.batch(data,len(data))

    def batch(self, data, packet_bytes):
        count = len(data)//packet_bytes
        if len(data) % packet_bytes or not 1 <= count <= self.max_batch_packets:
            raise ValueError('Invalid emulated batch')
        k = (packet_bytes-16)//32
        raw = np.frombuffer(data,dtype=np.uint8).reshape(count,packet_bytes)
        for header in raw[:,:16]:
            if struct.unpack('<IIII',header.tobytes()) != (MAGIC,k,0,0):
                raise ValueError('Bad emulated header')
        rows = raw[:,16:].view(np.int8).reshape(count,2,k,16).astype(np.int32)
        result = rows[:,0].transpose(0,2,1) @ rows[:,1]
        self.ioctl_calls += 1
        self.tile_packets += count
        self.input_bytes_sent += len(data)
        return result.astype('<i4').tobytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--device')
    modes.add_argument('--emulate',action='store_true')
    parser.add_argument('--report',type=Path)
    args = parser.parse_args()
    rng = np.random.default_rng(8462)
    transport = DMADevice(args.device,batch_size=128) if args.device else EmulatedBatch()
    tests = []
    try:
        # nr2 with each exact supported count, including count=1.
        for k in (1,17,257,1024):
            for count in (1,2,7,32,64,128):
                x = rng.integers(-128,128,(count,k,16),dtype=np.int16).astype(np.int8)
                w = rng.integers(-128,128,(count,16,k),dtype=np.int16).astype(np.int8)
                data = b''.join(packet(x[i],w[i]) for i in range(count))
                expected = w.astype(np.int64) @ x.astype(np.int64)
                started = time.perf_counter()
                response = transport.batch(data,16+32*k)
                seconds = time.perf_counter()-started
                if len(response) != count*OUTPUT_BYTES:
                    raise AssertionError('Incomplete batch output')
                actual = np.frombuffer(response,dtype='<i4').reshape(count,16,16).transpose(0,2,1)
                np.testing.assert_array_equal(actual,expected)
                tests.append({'kind':'uniform_batch','k':k,'count':count,'seconds':seconds,
                              'seconds_per_tile':seconds/count,'exact':True})
        # Single transport fallback is an explicit size=1 configuration.
        for limit in (1,2,7,32,64,128):
            transport.max_batch_packets = limit
            for k,t,o in ((33,19,21),(1025,35,49),(17,1,1)):
                x = rng.integers(-128,128,(k,t),dtype=np.int16).astype(np.int8)
                w = rng.integers(-128,128,(o,k),dtype=np.int16).astype(np.int8)
                expected = w.astype(np.int64) @ x.astype(np.int64)
                before_calls,before_tiles = transport.ioctl_calls,transport.tile_packets
                started = time.perf_counter()
                actual = pointwise(x,w,transport)
                seconds = time.perf_counter()-started
                np.testing.assert_array_equal(actual,expected)
                tile_count = transport.tile_packets-before_tiles
                tests.append({'kind':'pointwise','k':k,'times':t,'outputs':o,'batch_size':limit,
                              'seconds':seconds,'seconds_per_tile':seconds/tile_count,
                              'ioctl_calls':transport.ioctl_calls-before_calls,
                              'tile_packets':tile_count,'exact':True})
        report = {'hardware_execution':bool(args.device),'device':args.device,
                  'all_exact':True,'ioctl_calls':transport.ioctl_calls,
                  'tile_packets':transport.tile_packets,'input_bytes':transport.input_bytes_sent,
                  'total_transport_test_seconds':sum(t['seconds'] for t in tests),'tests':tests}
        if args.report:
            args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='tests'},indent=2))
    finally:
        if args.device:
            transport.close()


if __name__ == '__main__':
    main()
