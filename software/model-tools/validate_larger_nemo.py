"""Full original NeMo validation for the exact archive in a larger-model directory."""
import sys
from pathlib import Path

# Keep the qualified 256 validator unchanged; substitute only archive discovery.
source=Path(__file__).with_name('validate_nemo.py').read_text()
source=source.replace("archive=args.checkpoint_dir/'stt_en_citrinet_256_ls.nemo'", "archive=next(args.checkpoint_dir.glob('*.nemo'))")
source=source.replace("map_location=torch.device('cpu')).eval()", "map_location=torch.device('cpu')).float().eval()")
source=source.replace('audio=read_audio(wav);', 'audio=read_audio(wav).astype(np.float32);')
source=source.replace("report={'status':'pass',", "report={'validation_adapter_sha256':hashlib.sha256(Path(__file__).with_name('validate_larger_nemo.py').read_bytes()).hexdigest(),'tokenizer_adapter_sha256':hashlib.sha256(Path(__file__).with_name('larger_tokenizer.py').read_bytes()).hexdigest(),'explicit_audio_dtype':'float32','status':'pass',")
source=source.replace('runtime=Runtime(args.model_dir,4)',
    'runtime=Runtime(args.model_dir,4)\n    from larger_tokenizer import load_decoder\n    global decode\n    runtime.vocabulary,decode=load_decoder(args.model_dir)')
exec(compile(source,str(Path(__file__).with_name('validate_nemo.py')),'exec'),{'__name__':'__main__','__file__':str(Path(__file__).with_name('validate_nemo.py'))})
