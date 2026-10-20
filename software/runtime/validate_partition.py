"""Full exported-graph partition parity; no physical or NeMo-wrapper claim."""
import json
from pathlib import Path
import numpy as np
import onnxruntime as ort
from partition import PartitionGraph,options

def main():
    path=Path(__file__).resolve().parents[2]/'research/export/citrinet-256-ls/model.onnx'
    full=ort.InferenceSession(str(path),options(4),providers=['CPUExecutionProvider'])
    part=PartitionGraph(path,emulate=True,fp32_partition=True)
    rows=[];rng=np.random.default_rng(4)
    for t,length in [(32,31),(48,33),(80,65)]:
        feed={'features':rng.normal(size=(1,80,t)).astype(np.float32),'feature_lengths':np.array([length],np.int64)}
        original=full.run(None,feed);split=part.run(feed)
        error=float(np.max(np.abs(original[0]-split[0])))
        np.testing.assert_allclose(original[0],split[0],rtol=2e-4,atol=2e-4)
        np.testing.assert_array_equal(original[1],split[1])
        rows.append({'time':t,'valid':length,'max_abs_logprob_error':error,'encoded_lengths_equal':True})
    report={'physical_board':False,'fp32_partition_parity':rows,'accelerated_nodes':len(part.accelerated_nodes),'steps':len(part.steps),
            'limits':['Not original NeMo wrapper waveform parity','Not INT8 WER or physical accelerator validation']}
    Path(__file__).with_name('partition_validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
