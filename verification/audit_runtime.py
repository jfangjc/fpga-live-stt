"""Independent frontend formula and whole-graph emulation probes."""
import json
import sys
from pathlib import Path
import numpy as np
import torch
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'software/model-tools'))
sys.path.insert(0,str(ROOT/'software/runtime'))
from citrinet_cpu import Frontend
from partition import PartitionGraph,options

def main():
    folder=ROOT/'research/export/citrinet-256-ls'; f=Frontend(folder)
    c=np.load(folder/'frontend.npz'); rows=[]
    torch.set_num_threads(4); rng=np.random.default_rng(644)
    for n in [320,1600,16003]:
        a=(rng.normal(size=n)*.001).astype('float32'); y,l=f(a)
        t=torch.from_numpy(a); t=torch.cat((t[:1],t[1:]-.97*t[:-1]))
        s=torch.stft(t,n_fft=512,hop_length=160,win_length=400,
            window=torch.from_numpy(c['window']),center=True,pad_mode='reflect',return_complex=True)
        z=torch.log(torch.from_numpy(c['fb']).reshape(80,257)@s.abs().pow(2)+2**-24)
        z=(z-z.mean(1,keepdim=True))/(z.std(1,keepdim=True)+1e-5)
        delta=float(np.abs(y[0,:,:int(l[0])]-z.numpy()).max())
        assert np.isfinite(y).all() and delta<1e-3
        assert int(l[0])==n//160+1 and y.shape[-1]%16==0
        rows.append(dict(samples=n,valid=int(l[0]),shape=list(y.shape),max_abs_error=delta))
    silence,l=f(np.zeros(320,dtype='float32')); assert np.isfinite(silence).all()
    graph=PartitionGraph(folder/'model.onnx',4,emulate=True)
    x=np.random.default_rng(953).normal(size=(1,80,96)).astype('float32')
    feed={'features':x,'feature_lengths':np.array([65],dtype='int64')}
    a=graph.run(feed); b=ort.InferenceSession(str(folder/'model.onnx'),options(4),providers=['CPUExecutionProvider']).run(None,feed)
    assert np.array_equal(a[1],b[1]) and np.isfinite(a[0]).all()
    report=dict(frontend_formula_checks=rows,silence_finite=True,
        physical_hardware=False,full_original_nemo_parity=False,
        accelerated_nodes=len(graph.accelerated_nodes),partition_steps=len(graph.steps),
        quantized_vs_fp32_logit_max_abs_error=float(np.abs(a[0]-b[0]).max()),
        argmax_agreement_fraction=float(np.mean(a[0].argmax(-1)==b[0].argmax(-1))),
        encoded_lengths_equal=True,
        limitations=['Frontend reference is independently written torch formula using actual checkpoint constants, not full original NeMo preprocessor','Random features are not held-out recognition accuracy','Partitioned execution creates many CPU regions; initialization and warm overhead require KV260 measurement'])
    (ROOT/'verification/runtime_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
