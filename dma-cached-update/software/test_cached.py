#!/usr/bin/env python3
"""Host wire-format, error propagation and pinned-graph parity checks."""
import ctypes
import json
from pathlib import Path
import struct
import sys
import types
import unittest
from unittest.mock import patch
import numpy as np
import qn_cached as cached
from cached_smoke import EmulatedCached


class ProtocolTests(unittest.TestCase):
    def test_known_wire_layout(self):
        w = np.arange(34,dtype=np.int8).reshape(17,2)
        p = cached.load_packet(w,0x123)
        self.assertEqual(struct.unpack('<IIII',p[:16]),(0x32434e51,0x00110001,2,0x123))
        self.assertEqual(len(p),80)
        self.assertEqual(list(p[16:32]),list(range(0,32,2)))
        self.assertEqual(list(p[32:48]),list(range(1,33,2)))
        self.assertEqual(list(p[48:64]),[32]+[0]*15)
        x = np.array([[1,2],[-128,127]],dtype=np.int8)
        p = cached.run_packet(x,17,0x123)
        self.assertEqual(struct.unpack('<IIII',p[:16]),(cached.MAGIC,0x00110002,2,0x123))
        self.assertEqual(p[16:32],bytes([1,2]+[0]*14))
        self.assertEqual(p[32:48],bytes([128,127]+[0]*14))

    def test_unpack_independent_layout(self):
        sums = np.arange(512,dtype='<i4').reshape(2,16,16)
        response = struct.pack('<IIII',cached.RESPONSE_MAGIC,0,3|(17<<16),4)+sums.tobytes()
        out = cached.unpack(response,17,2,k=3,tag=4)
        self.assertEqual(out.shape,(17,2))
        self.assertEqual(out[0].tolist(),[0,16])
        self.assertEqual(out[16].tolist(),[256,272])

    def test_invalid_types_dimensions(self):
        for weights in (np.ones((1,1)),np.zeros((0,2),dtype=np.int8),np.zeros((1025,1),dtype=np.int8)):
            with self.assertRaises((TypeError,ValueError)):
                cached.load_packet(weights)
        for tag in (0,-1,0x100000000):
            with self.assertRaises(ValueError):
                cached.load_packet(np.zeros((1,1),dtype=np.int8),tag)
        for x in (np.zeros((2,17),dtype=np.int8),np.zeros((0,1),dtype=np.int8),np.zeros((2,1))):
            with self.assertRaises((TypeError,ValueError)):
                cached.run_packet(x,1)

    def test_bad_acknowledgements(self):
        base = (cached.RESPONSE_MAGIC,0,3|(17<<16),4)
        for index,value in ((0,0),(1,3),(2,1),(3,5)):
            fields = list(base)
            fields[index] = value
            with self.assertRaises((RuntimeError,ValueError)):
                cached.validate_response(struct.pack('<IIII',*fields),3,17,4)
        with self.assertRaises(ValueError):
            cached.unpack(struct.pack('<IIII',*base),17,k=3,tag=4)

    def test_fault_does_not_replay_or_retain_cache(self):
        device = EmulatedCached()
        device.load(np.zeros((17,2),dtype=np.int8))
        calls = []
        def bad(data,size):
            calls.append(1)
            return bytes(size)
        device.transaction = bad
        with self.assertRaises(ValueError):
            device.run(np.zeros((2,1),dtype=np.int8),17)
        self.assertIsNone(device.loaded)
        self.assertEqual(len(calls),1)

    def test_nr3_ioctl_abi(self):
        device = EmulatedCached()
        request_sizes = []
        def ioctl(fd,nr,request):
            self.assertEqual(nr,0xc0205103)
            self.assertEqual(len(request),32)
            tx,rx,txbytes,rxbytes,flags,reserved = struct.unpack('=QQIIII',request)
            self.assertEqual((flags,reserved),(0,0))
            payload = ctypes.string_at(tx,txbytes)
            emulation = EmulatedCached()
            response = emulation.transaction(payload,rxbytes)
            ctypes.memmove(rx,response,rxbytes)
            request_sizes.append((txbytes,rxbytes))
        # Portable host test injects fcntl because Windows does not provide it.
        with patch.dict(sys.modules,{'fcntl':types.SimpleNamespace(ioctl=ioctl)}):
            response = cached.CachedDMADevice.transaction(device,cached.load_packet(np.ones((17,2),dtype=np.int8)),16)
        cached.validate_response(response,2,17,1)
        self.assertEqual(request_sizes,[(80,16)])

    def test_emulator_errors_invalidate_cache(self):
        device = EmulatedCached()
        w = np.ones((1,2),dtype=np.int8)
        x = np.ones((2,1),dtype=np.int8)
        for packet,size,status in (
            (struct.pack('<IIII',cached.MAGIC,0x101,2,1),16,1),
            (cached.load_packet(w,1)[:-16],16,2),
            (cached.run_packet(x,1,2),cached.output_bytes(1),3),
            (struct.pack('<IIII',cached.MAGIC,cached.INVALIDATE,0,0)+bytes(16),16,2)):
            device.load(w)
            response = device.transaction(packet,size)
            self.assertEqual(struct.unpack('<IIII',response[:16])[1],status)
            self.assertIsNone(device.cache)
            response = device.transaction(cached.run_packet(x,1,device.tag),cached.output_bytes(1))
            self.assertEqual(struct.unpack('<IIII',response[:16])[1],3)
            self.assertEqual(response[16:],bytes(cached.output_bytes(1)-16))

    def test_nr4_batch_abi_k1_and_ordering(self):
        device,service = EmulatedCached(),EmulatedCached()
        w = np.arange(17,dtype=np.int8).reshape(17,1)
        device.load(w)
        service.load(w)
        requests = []
        def ioctl(fd,nr,request):
            self.assertEqual((nr,len(request)),(0xc0205104,32))
            tx,rx,packet_bytes,response_bytes,count,reserved = struct.unpack('=QQIIII',request)
            self.assertEqual((packet_bytes,response_bytes,count,reserved),(32,2064,2,0))
            raw = ctypes.string_at(tx,packet_bytes*count)
            response = service.batch_transaction(raw,packet_bytes,response_bytes,count)
            ctypes.memmove(rx,response,len(response))
            requests.append(1)
        device.batch_transaction = types.MethodType(cached.CachedDMADevice.batch_transaction,device)
        x = np.arange(19,dtype=np.int8).reshape(1,19)
        with patch.dict(sys.modules,{'fcntl':types.SimpleNamespace(ioctl=ioctl)}):
            actual = device.run_many(x,17)
        np.testing.assert_array_equal(actual,w.astype(np.int64) @ x.astype(np.int64))
        self.assertEqual(len(requests),1)
        self.assertEqual(device.run_commands,2)
        self.assertEqual(device.ioctl_calls,2)  # one LOAD and one RUN batch

    def test_batch_bounds_and_partial_ack_failure(self):
        device = EmulatedCached()
        w = np.ones((1024,1),dtype=np.int8)
        device.load(w)
        self.assertEqual(cached.MAX_BATCH_RX_BYTES//cached.output_bytes(1024),2)
        with patch.dict(sys.modules,{'fcntl':types.SimpleNamespace(ioctl=lambda *args:self.fail('Invalid batch reached ioctl'))}):
            for count in (0,3,129):
                with self.assertRaises(ValueError):
                    cached.CachedDMADevice.batch_transaction(device,bytes(32*max(0,count)),32,65552,count)
        device.load(np.ones((1,1),dtype=np.int8))
        calls = []
        def bad_batch(data,pbytes,rbytes,count):
            calls.append(1)
            good = struct.pack('<IIII',cached.RESPONSE_MAGIC,0,1|(1<<16),device.tag)+bytes(rbytes-16)
            return good+bytes(rbytes)
        device.batch_transaction = bad_batch
        with self.assertRaises(ValueError):
            device.run_many(np.ones((1,17),dtype=np.int8),1)
        self.assertIsNone(device.loaded)
        self.assertEqual(len(calls),1)


def graph_parity():
    sys.path.insert(0,str(Path(__file__).parent/'asr-baseline'))
    from quartznet_hybrid import Graph
    model = Path(__file__).parent/'asr-baseline/model/model.onnx'
    rng = np.random.default_rng(29520)
    features = rng.normal(size=(1,64,43)).astype(np.float32)
    reference = Graph(model,mode='emulate')
    outputs = {}
    reference.run(features,observer=lambda node,y:outputs.__setitem__(node.name,y.copy()))
    transport = EmulatedCached()
    graph = Graph(model,mode='dma',transact=transport,pointwise_backend='cached')
    checked = []
    def check(node,y):
        np.testing.assert_array_equal(y,outputs[node.name],err_msg=node.name)
        checked.append(node.name)
    graph.run(features,observer=check)
    result = {'hardware_execution':False,'all_nodes_exact':True,'nodes':len(checked),
              'pointwise_nodes':len(graph.quantized),'load_commands':transport.load_commands,
              'run_commands':transport.run_commands,'input_bytes':transport.input_bytes_sent,
              'output_bytes':transport.output_bytes_received}
    print(json.dumps(result,indent=2))
    return result


if __name__ == '__main__':
    result = unittest.main(argv=[sys.argv[0]],exit=False).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if '--graph' in sys.argv:
        result = graph_parity()
        (Path(__file__).parents[1]/'reports/cached_graph_parity.json').write_text(json.dumps(result,indent=2)+'\n')
