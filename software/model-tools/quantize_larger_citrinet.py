"""Run existing calibrated convolution quantizer with legacy ORT compatibility."""
import inspect,sys
from pathlib import Path
import onnxruntime.quantization as quant
original=quant.quantize_static
if 'calibration_providers' not in inspect.signature(original).parameters:
    def legacy(*args,**kwargs):
        kwargs.pop('calibration_providers',None)
        return original(*args,**kwargs)
    quant.quantize_static=legacy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fused'))
if __name__=='__main__':
    path=Path(__file__).resolve().parents[1]/'fused/build_cpu_int8.py'
    source=path.read_text().replace('quantize_static(copy.deepcopy(model),',"quantize_static(str(args.model_dir/'model.onnx'),")
    # Folded/pruned gamma-0.25 channels have subnormal weight scales. Prevent
    # undefined INT32 bias casts and require fresh accuracy validation.
    source=source.replace("calibration_providers=['CPUExecutionProvider'])",
        "calibration_providers=['CPUExecutionProvider'], extra_options={'MinimumRealRange':0.01})")
    source=source.replace("vocab = (args.model_dir/'vocab.txt').read_text().splitlines()",
        'from larger_tokenizer import load_decoder\n    global decode\n    vocab,decode=load_decoder(args.model_dir)')
    exec(compile(source,str(path),'exec'),{'__name__':'__main__','__file__':str(path)})
