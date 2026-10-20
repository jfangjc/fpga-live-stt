"""Independent structural/checkpoint/export checks; not full NeMo restore parity."""
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
import torch
import yaml

ROOT = Path(__file__).resolve().parents[1]

def main():
    spec = importlib.util.spec_from_file_location('exporter', ROOT/'software/model-tools/export_citrinet.py')
    exporter = importlib.util.module_from_spec(spec); spec.loader.exec_module(exporter)
    ckpt = ROOT/'research/checkpoints/citrinet-256-ls'
    config = yaml.safe_load((ckpt/'model_config.yaml').read_text())
    state = torch.load(ckpt/'model_weights.ckpt',map_location='cpu',weights_only=True)
    torch.set_num_threads(4)
    reference = exporter.Model(config,state)
    path = ROOT/'research/export/citrinet-256-ls/model.onnx'
    graph = onnx.load(path); onnx.checker.check_model(graph)
    options=ort.SessionOptions(); options.intra_op_num_threads=4
    session=ort.InferenceSession(str(path),options,providers=['CPUExecutionProvider'])
    checks=[]
    rng=np.random.default_rng(619315)
    for frames,valid in [(96,65),(513,499)]:
        x=rng.normal(0,1,(1,80,frames)).astype('float32'); lens=np.array([valid],dtype=np.int64)
        with torch.no_grad(): y, l=reference(torch.from_numpy(x.copy()),torch.from_numpy(lens))
        actual,length=session.run(None,{'features':x,'feature_lengths':lens})
        np.testing.assert_allclose(y.numpy(),actual,atol=5e-4,rtol=5e-4)
        np.testing.assert_array_equal(l.numpy(),length)
        checks.append(dict(frames=frames,valid=valid,encoded_length=length.tolist(),max_abs_error=float(np.abs(y.numpy()-actual).max()),argmax_equal=bool(np.array_equal(y.numpy().argmax(-1),actual.argmax(-1)))))
    operators={}
    for n in graph.graph.node: operators[n.op_type]=operators.get(n.op_type,0)+1
    report=dict(checkpoint_tokenizer_type=config['tokenizer']['type'],
        feature_channels=config['preprocessor']['features'],
        pad_to=config['preprocessor']['pad_to'],
        se_contexts=sorted(set(b['se_context_size'] for b in config['encoder']['jasper'])),
        model_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        checks=checks,operators=operators,
        full_original_nemo_wrapper_parity=False,frontend_parity=False,tokenizer_parity=False,
        limitations=['Reference reuses pinned exporter construction; independent random probes do not independently prove full NeMo model reconstruction','Zero-length feature input causes masked SE division by zero; reject empty/too-short audio or define original validated behavior','WordPiece vocabulary ## continuation tokens require matching WordPiece decoder; not SentencePiece','Global SE context and symmetric convolution imply no demonstrated causal streaming'])
    (ROOT/'verification/model_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
