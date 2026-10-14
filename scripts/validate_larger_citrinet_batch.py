"""Validate both requested models in one pinned NeMo process."""
import runpy,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'software/model-tools'))
for checkpoint,export in [('citrinet-512-ls','citrinet-512-ls'),('citrinet-1024-ls','citrinet-1024-gamma-0.25')]:
    sys.argv=['validate_larger_nemo.py','--checkpoint-dir',str(root/'research/checkpoints'/checkpoint),
              '--model-dir',str(root/'research/export'/export),'--output',str(root/'research/export'/export/'nemo_validation.json'),
              str(root/'research/eval/user-recording/speech.wav'),str(root/'research/eval/librispeech-mini/evaluation/6930-75918-0000.wav')]
    runpy.run_path(str(root/'software/model-tools/validate_larger_nemo.py'),run_name='__main__')
