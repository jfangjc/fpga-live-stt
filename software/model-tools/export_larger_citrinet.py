"""Use the existing pinned exporter with legacy Torch 2.2 export signature."""
import inspect
from pathlib import Path
import torch

original=torch.onnx.export
if 'dynamo' not in inspect.signature(original).parameters:
    def legacy_export(*args, **kwargs):
        kwargs.pop('dynamo',None)
        return original(*args, **kwargs)
    torch.onnx.export=legacy_export

if __name__=='__main__':
    path=Path(__file__).with_name('export_citrinet.py')
    source=path.read_text().replace("residual_mode=b.get('residual_mode', 'add'), layer_idx=i)",
        "residual_mode=b.get('residual_mode', 'add'), kernel_size_factor=b.get('kernel_size_factor',1), layer_idx=i)")
    exec(compile(source,str(path),'exec'),{'__name__':'__main__','__file__':str(path)})
