#!/usr/bin/env python3
"""QNC2 cached layer checks. --emulate is numerical protocol emulation only."""
import argparse
import json
from pathlib import Path
import struct
import time
import numpy as np
from qn_cached import (CachedDMADevice,MAGIC,RESPONSE_MAGIC,LOAD,RUN,INVALIDATE,
                       MAX_BATCH_RX_BYTES,MAX_BATCH_PACKETS,output_bytes,pointwise)


class EmulatedCached(CachedDMADevice):
    """Independent packet consumer, not an FPGA timing or driver model."""
    def __init__(self,cached_batch_size=128):
        self.fd = 1
        self.max_batch_packets = cached_batch_size
        self.ioctl_calls = self.tile_packets = self.input_bytes_sent = self.output_bytes_received = 0
        self.load_commands = self.run_commands = self.invalidate_commands = self.tag = 0
        self.loaded = self.cache = None

    def close(self):
        self.fd = None
        self.loaded = self.cache = None

    def transaction(self,data,response_bytes):
        magic,control,k,tag = struct.unpack('<IIII',data[:16])
        op,m = control & 255,control>>16
        status = 0
        payload = b''
        if magic != MAGIC or control & 0xff00 or k & 0xffff0000 or op not in (LOAD,RUN,INVALIDATE):
            status = 1
        elif op == INVALIDATE:
            if k or m or tag:
                status = 1
            elif len(data) != 16:
                status = 2
            self.cache = None
        elif not 1 <= k <= 1024 or not 1 <= m <= 1024 or not tag:
            status = 1
        elif op == LOAD:
            self.cache = None
            blocks = (m+15)//16
            if len(data) != 16+blocks*k*16:
                status = 2
            else:
                raw = np.frombuffer(data,offset=16,dtype=np.int8).reshape(blocks,k,16)
                weights = raw.transpose(0,2,1).reshape(blocks*16,k).copy()
                self.cache = (k,m,tag,weights)
        elif op == RUN:
            payload = bytes(output_bytes(m)-16)
            if len(data) == 16:
                status = 2
            elif self.cache is None or self.cache[:3] != (k,m,tag):
                status = 3
            elif len(data) != 16+16*k:
                status = 2
            else:
                x = np.frombuffer(data,offset=16,dtype=np.int8).reshape(k,16)
                sums = self.cache[3].astype(np.int64) @ x.astype(np.int64)
                payload = sums.reshape((m+15)//16,16,16).transpose(0,2,1).astype('<i4').tobytes()
        if status:
            self.cache = None
        response = struct.pack('<IIII',RESPONSE_MAGIC,status,(k&0xffff)|(m<<16),tag)+payload
        if len(response) != response_bytes:
            raise ValueError('Incorrect expected response length')
        self.ioctl_calls += 1
        self.input_bytes_sent += len(data)
        self.output_bytes_received += len(response)
        return response

    def batch_transaction(self,data,packet_bytes,response_bytes,count):
        if not 1 <= count <= min(self.max_batch_packets,MAX_BATCH_PACKETS) or \
           not 32 <= packet_bytes <= 16400 or packet_bytes % 16 or \
           not 1040 <= response_bytes <= 65552 or (response_bytes-16) % 1024 or \
           len(data) != packet_bytes*count or count*response_bytes > MAX_BATCH_RX_BYTES:
            raise ValueError('Invalid emulated cached RUN batch bounds')
        data = memoryview(data).cast('B')
        first_header = bytes(data[:16])
        _,control,_,_ = struct.unpack('<IIII',first_header)
        if control & 255 != RUN:
            raise ValueError('Batches accept RUN packets only')
        for index in range(count):
            if bytes(data[index*packet_bytes:index*packet_bytes+16]) != first_header:
                raise ValueError('Cached batch headers must be identical')
        responses = []
        before_calls = self.ioctl_calls
        for index in range(count):
            response = self.transaction(data[index*packet_bytes:(index+1)*packet_bytes],response_bytes)
            responses.append(response)
        self.ioctl_calls = before_calls+1
        return b''.join(responses)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--device')
    modes.add_argument('--emulate',action='store_true')
    parser.add_argument('--report',type=Path)
    args = parser.parse_args()
    transport = CachedDMADevice(args.device) if args.device else EmulatedCached()
    rng = np.random.default_rng(93458)
    tests = []
    try:
        transport.invalidate()
        for k,m,t in ((1,1,1),(17,29,19),(257,33,35),(1024,16,17),(512,1024,19),
                      (1024,1024,16),(64,256,37),(512,512,31),(1024,29,16)):
            x = rng.integers(-128,128,(k,t),dtype=np.int16).astype(np.int8)
            w = rng.integers(-128,128,(m,k),dtype=np.int16).astype(np.int8)
            before = transport.ioctl_calls
            started = time.perf_counter()
            actual = pointwise(x,w,transport)
            elapsed = time.perf_counter()-started
            np.testing.assert_array_equal(actual,w.astype(np.int64) @ x.astype(np.int64))
            limit = min(transport.max_batch_packets,MAX_BATCH_RX_BYTES//output_bytes(m))
            expected_calls = 1+(((t+15)//16)+limit-1)//limit
            if transport.ioctl_calls-before != expected_calls:
                raise AssertionError('Incorrect bounded LOAD/RUN batch ioctl count')
            tests.append({'k':k,'m':m,'t':t,'exact':True,'seconds':elapsed,
                          'ioctl_calls':transport.ioctl_calls-before})
        # Worst signed input/weight product tests and replacement of same dims.
        for value in (-128,127):
            x = np.full((1024,17),value,dtype=np.int8)
            w = np.full((17,1024),value,dtype=np.int8)
            np.testing.assert_array_equal(pointwise(x,w,transport),w.astype(np.int64) @ x.astype(np.int64))
        for cap,k,m,t in ((1,1,1,33),(3,17,29,81),(128,1,16,2048),
                           (128,1,17,1025),(128,1024,1024,33)):
            transport.max_batch_packets = cap
            x = rng.integers(-128,128,(k,t),dtype=np.int16).astype(np.int8)
            w = rng.integers(-128,128,(m,k),dtype=np.int16).astype(np.int8)
            before_calls,before_runs = transport.ioctl_calls,transport.run_commands
            actual = pointwise(x,w,transport)
            np.testing.assert_array_equal(actual,w.astype(np.int64) @ x.astype(np.int64))
            limit = min(cap,MAX_BATCH_RX_BYTES//output_bytes(m))
            blocks = (t+15)//16
            if transport.ioctl_calls-before_calls != 1+(blocks+limit-1)//limit or transport.run_commands-before_runs != blocks:
                raise AssertionError('Incorrect bounded RUN batching counters')
            tests.append({'kind':'batch_limit','cap':cap,'k':k,'m':m,'t':t,'exact':True,
                          'ioctl_calls':transport.ioctl_calls-before_calls,'run_commands':blocks})
        transport.max_batch_packets = 128
        transport.invalidate()
        try:
            transport.run(np.zeros((1024,1),dtype=np.int8),17)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalidation must reject RUN')
        lease_checked = False
        if args.device:
            import errno
            x = np.ones((2,1),dtype=np.int8)
            w = np.ones((1,2),dtype=np.int8)
            transport.load(w)
            with CachedDMADevice(args.device) as other:
                other.load(w)
                try:
                    transport.run(x,1)
                except OSError as error:
                    if error.errno != errno.ESTALE:
                        raise
                else:
                    raise AssertionError('Competing LOAD must reject stale cache lease')
                np.testing.assert_array_equal(other.run(x,1),[[2]])
            # Stale failure propagates; recovery is an explicit new LOAD.
            transport.load(w)
            np.testing.assert_array_equal(transport.run(x,1),[[2]])
            lease_checked = True
        report = {'hardware_execution':bool(args.device),'device':args.device,'all_exact':True,
                  'cross_fd_lease_checked':lease_checked,
                  'load_commands':transport.load_commands,'run_commands':transport.run_commands,
                  'invalidate_commands':transport.invalidate_commands,
                  'computed_tile_groups':transport.tile_packets,
                  'dma_command_packets':transport.load_commands+transport.run_commands+transport.invalidate_commands,
                  'ioctl_calls':transport.ioctl_calls,'input_bytes':transport.input_bytes_sent,
                  'output_bytes':transport.output_bytes_received,'tests':tests}
        if args.report:
            args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='tests'},indent=2))
    finally:
        transport.close()


if __name__ == '__main__':
    main()
