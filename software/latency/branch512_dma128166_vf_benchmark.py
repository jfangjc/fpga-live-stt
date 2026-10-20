"""Qualified graph/library with byte-identical valid-frame preprocessing."""
from branch512_dma128166_irq_benchmark import *
from branch512_dma128166_irq_benchmark import AudioTimer as ParentTimer,bindings as parent_bindings,artifacts as parent_artifacts
from frontend_valid_frames import ValidFrameFrontend

def artifacts():
    path=ROOT/'reports/fused/valid_frame_frontend_validation.json'
    p=json.loads(path.read_text())
    assert p['complete'] and p['all_model_inputs_bit_exact'] and len(p['cases'])==71
    assert p['candidate_sha256']==sha(ROOT/'software/latency/frontend_valid_frames.py')
    assert p['pinned_frontend_sha256']==sha(ROOT/'software/model-tools/citrinet_cpu.py')
    items=parent_artifacts();items['valid_frame_validation']=path
    return items

class AudioTimer(ParentTimer):
    def __init__(self,items):
        super().__init__(items)
        self.frontend=ValidFrameFrontend(items['directory'])

def bindings(items):
    return parent_bindings(items)|{'valid_frame_validation_sha256':sha(items['valid_frame_validation']),
        'valid_frame_frontend_sha256':sha(ROOT/'software/latency/frontend_valid_frames.py'),
        'timer_source_sha256':sha(__file__)}
