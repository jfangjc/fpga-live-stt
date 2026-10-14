"""Prepare fair full-path validation; preserve all existing benchmarks."""
import ast
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def save(name, text):
    ast.parse(text)
    path = ROOT/name
    if path.exists(): assert path.read_text() == text, path
    else: path.write_text(text, newline='\n')

guard = '''
validation_path=ROOT/'reports/fused/valid_frame_frontend_validation.json'
validation=json.loads(validation_path.read_text())
assert validation['complete'] and validation['all_model_inputs_bit_exact'] and len(validation['cases'])==71
assert validation['candidate_sha256']==sha(ROOT/'software/latency/frontend_valid_frames.py')
assert validation['pinned_frontend_sha256']==sha(ROOT/'software/model-tools/citrinet_cpu.py')
'''
cpu = (ROOT/'software/latency/tune_branch512_ab166_cpu.py').read_text()
cpu = cpu.replace('from se_pool import transform as pool', 'from frontend_valid_frames import ValidFrameFrontend\nfrom se_pool import transform as pool')
cpu = cpu.replace("path=ROOT/'research/fused/cpu-int8-cse.onnx'", guard+"\npath=ROOT/'research/fused/cpu-int8-cse.onnx'")
cpu = cpu.replace("frontend=Frontend(ROOT/'research/export/citrinet-256-ls')", "frontend=ValidFrameFrontend(ROOT/'research/export/citrinet-256-ls')")
cpu = cpu.replace("'candidate_count':64", "'valid_frame_validation_sha256':sha(validation_path),'valid_frame_frontend_sha256':validation['candidate_sha256'],'candidate_count':64")
save('software/latency/tune_valid_frame_cpu.py', cpu)
isolated = (ROOT/'software/latency/confirm_branch512_ab166_cpu_isolated.py').read_text()
isolated = isolated.replace('from chain_benchmark import make_session', 'from frontend_valid_frames import ValidFrameFrontend\nfrom chain_benchmark import make_session')
isolated = isolated.replace('branch512_ab166_cpu_policy_wide.json', 'valid_frame_cpu_policy.json')
isolated = isolated.replace('original = onnx.load(model_path)', guard+'\noriginal = onnx.load(model_path)')
isolated = isolated.replace('frontend = Frontend(directory)', 'frontend = ValidFrameFrontend(directory)')
isolated = isolated.replace("'source_sha256': sha(__file__)", "'valid_frame_validation_sha256':sha(validation_path),'valid_frame_frontend_sha256':validation['candidate_sha256'],'source_sha256':sha(__file__)")
save('software/latency/confirm_valid_frame_cpu_isolated.py', isolated)

for platform in ('branch512_ab166', 'branch512_dma128166'):
    label = platform+'_vf'
    wrapper = f'''"""Qualified graph/library with byte-identical valid-frame preprocessing."""
from {platform}_irq_benchmark import *
from {platform}_irq_benchmark import AudioTimer as ParentTimer,bindings as parent_bindings,artifacts as parent_artifacts
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
    return parent_bindings(items)|{{'valid_frame_validation_sha256':sha(items['valid_frame_validation']),
        'valid_frame_frontend_sha256':sha(ROOT/'software/latency/frontend_valid_frames.py'),
        'timer_source_sha256':sha(__file__)}}
'''
    save(f'software/latency/{label}_benchmark.py', wrapper)
    validation = (ROOT/'software/latency/validate_branch512_ab166_neon_maskfast_physical.py').read_text()
    validation = validation.replace('branch512_ab166_neon_maskfast_benchmark', label+'_benchmark')
    save(f'software/latency/validate_{label}_physical.py', validation)
    tune = (ROOT/'software/latency/tune_branch512_ab166_irq_policy.py').read_text()
    tune = tune.replace('branch512_ab166_irq_benchmark', label+'_benchmark')
    tune = tune.replace('branch512_ab166_cpu_policy_wide.json', 'valid_frame_cpu_policy.json')
    tune = tune.replace("assert cpu_screen['candidate_count']==64", "assert cpu_screen['candidate_count']==64\nassert cpu_screen['valid_frame_frontend_sha256']==sha(ROOT/'software/latency/frontend_valid_frames.py')")
    save(f'software/latency/tune_{label}_policy.py', tune)
    confirm = (ROOT/'software/latency/confirm_branch512_ab166_irq_latency.py').read_text()
    confirm = confirm.replace('branch512_ab166_irq_benchmark', label+'_benchmark')
    confirm = confirm.replace('branch512_ab166_cpu_isolated_confirmation.json', 'valid_frame_cpu_isolated_confirmation.json')
    confirm = confirm.replace('confirm_branch512_ab166_cpu_isolated.py', 'confirm_valid_frame_cpu_isolated.py')
    anchor = "timer=AudioTimer(items);audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')"
    confirm = confirm.replace(anchor, "assert isolated['valid_frame_frontend_sha256']==bound['valid_frame_frontend_sha256']\n"+
        "original_isolated_path=ROOT/'reports/fused/branch512_ab166_cpu_isolated_confirmation.json'\n"+
        "original_isolated=json.loads(original_isolated_path.read_text());assert original_isolated['complete'] and not original_isolated['fpga_session_loaded']\n"+anchor)
    anchor = "summary['strongest_cpu_p50']=min(summary['cpu_p50'],isolated_cpu['cpu_p50'])"
    confirm = confirm.replace(anchor, "original_cpu=next(c for c in original_isolated['contexts'] if c['context_seconds']==seconds)\n        "+
        "summary['strongest_cpu_p50']=min(summary['cpu_p50'],isolated_cpu['cpu_p50'],original_cpu['cpu_p50'])")
    confirm = confirm.replace("min(summary['cpu_p95'],isolated_cpu['cpu_p95'])", "min(summary['cpu_p95'],isolated_cpu['cpu_p95'],original_cpu['cpu_p95'])")
    confirm = confirm.replace("'isolated_cpu_confirmation_sha256':sha(isolated_path)", "'isolated_cpu_confirmation_sha256':sha(isolated_path),'original_isolated_cpu_confirmation_sha256':sha(original_isolated_path)")
    save(f'software/latency/confirm_{label}_latency.py', confirm)
print('Prepared two isolated valid-frame hardware variants and fresh CPU screen/isolation; no benchmark started')
