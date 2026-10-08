"""Exercise weight rotation/tails against independent INT64 matrix products."""
import json
from pathlib import Path
import sys
import numpy as np
root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'software'))
from batch_smoke import EmulatedBatch
from qn_tile import pointwise
rng = np.random.default_rng(7052)
cases = 0
for limit in (2,7,32,64,128):
    transport = EmulatedBatch(limit)
    transport.accepts_buffer = True
    for k,t,o in ((17,113,35),(1031,37,81),(17,1,2081),(17,35,2081),(17,35,2047)):
        x = rng.integers(-128,128,(k,t),dtype=np.int8)
        w = rng.integers(-128,128,(o,k),dtype=np.int8)
        actual = pointwise(x,w,transport)
        np.testing.assert_array_equal(actual,w.astype(np.int64)@x.astype(np.int64))
        cases += 1
report = {'result':'PASS','hardware_execution':False,'independent_int64_cases':cases,
          'covers':'Odd output tile counts, output tiles exceeding batch limit, short final batch, K chunking, zero-copy input buffers'}
(root/'reports/dma_reuse_host.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
