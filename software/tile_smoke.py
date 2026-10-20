"""Physical DMA tile correctness/round-trip test; requires the V2 bitstream."""
import argparse
import json
import time
import numpy as np
from qn_tile import DMADevice, packet, unpack, pointwise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='/dev/qn-tile')
    args = parser.parse_args()
    rng = np.random.default_rng(260)
    results = []
    with DMADevice(args.device) as device:
        for k in (1,17,257,1024):
            x = rng.integers(-128,128,(k,16),dtype=np.int8)
            w = rng.integers(-128,128,(16,k),dtype=np.int8)
            data = packet(x,w)
            start = time.perf_counter()
            output = device(data)
            elapsed = time.perf_counter()-start
            actual = unpack(output)
            np.testing.assert_array_equal(actual,w.astype(np.int64) @ x.astype(np.int64))
            results.append({'k':k,'packet_bytes':len(data),'round_trip_seconds':elapsed})
        x = rng.integers(-128,128,(1031,33),dtype=np.int8)
        w = rng.integers(-128,128,(17,1031),dtype=np.int8)
        np.testing.assert_array_equal(pointwise(x,w,device),w.astype(np.int64) @ x.astype(np.int64))
    print(json.dumps({'result':'PASS','physical_dma_used':True,
                      'tiles':results,'tails_and_k_chunking':'PASS'},indent=2))


if __name__ == '__main__':
    main()
