"""Extend CPU placement tuning without modifying any qualified source."""
from pathlib import Path
import ast
ROOT = Path(__file__).resolve().parents[1]
old = 'branch512_ab166_neon_maskfast'
new = 'branch512_ab166_irq'

def save(path, content):
    ast.parse(content)
    target = ROOT/path
    if target.exists(): assert target.read_text() == content, target
    else: target.write_text(content, newline='\n')

benchmark = '''"""Same qualified graph/library with all four supported CPU IRQ placements."""
from branch512_ab166_neon_maskfast_benchmark import *
from branch512_ab166_neon_maskfast_benchmark import bindings as parent_bindings

def configure(core):
    assert core in (0,1,2,3)
    before=snapshot()
    try:
        for number in before:(Path('/proc/irq')/number/'smp_affinity_list').write_text(str(core))
        after=snapshot()
        assert all(v['effective']==str(core) for v in after.values())
    except BaseException:
        for number,value in before.items():(Path('/proc/irq')/number/'smp_affinity_list').write_text(value['requested'])
        raise
    return {'before':before,'after':after}

def bindings(items):
    return parent_bindings(items)|{'irq_placement_source_sha256':sha(__file__),
                                  'timer_source_sha256':sha(__file__)}
'''
save(f'software/latency/{new}_benchmark.py', benchmark)
tune=(ROOT/f'software/latency/tune_{old}_policy.py').read_text().replace(old,new)
start=tune.index("policies=[{'threads':t,")
end=tune.index('random.Random(',start)
tune=tune[:start]+'''# All previous winners used the pool graph. Keep that validated graph and
# extend the IRQ placements to workers 1/2, including original 0/3 controls.
policies=[{'threads':t,'spin':s,'level':level,'irq_core':irq,'graph':'pool'}
          for t,s,irqs in ((4,0,(0,1,2,3)),(4,10,(0,1,2,3)),
                           (3,0,(1,2)),(2,10,(1,2)))
          for level in ('extended','all') for irq in irqs]
assert len(policies)==24
'''+tune[end:]
save(f'software/latency/tune_{new}_policy.py',tune)
confirm=(ROOT/f'software/latency/confirm_{old}_latency.py').read_text().replace(old,new)
anchor="timer=AudioTimer(items);audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')"
assert anchor in confirm
confirm=confirm.replace(anchor,'''isolated_path=ROOT/'reports/fused/branch512_ab166_cpu_isolated_confirmation.json'
isolated=json.loads(isolated_path.read_text())
assert isolated['complete'] and not isolated['hardware_execution'] and not isolated['fpga_session_loaded']
assert isolated['cpu_model_sha256']==bound['cpu_model_sha256']
assert isolated['source_sha256']==sha(ROOT/'software/latency/confirm_branch512_ab166_cpu_isolated.py')
'''+anchor)
anchor="summary['meets_50_percent']=bool(summary['speedup_factor']>=2 and summary['fpga_p95']<summary['cpu_p95'])"
assert anchor in confirm
confirm=confirm.replace(anchor,'''isolated_cpu=next(c for c in isolated['contexts'] if c['context_seconds']==seconds)
        assert isolated_cpu['cpu_policy']==cpu_policy
        summary['isolated_cpu_p50']=isolated_cpu['cpu_p50']
        summary['strongest_cpu_p50']=min(summary['cpu_p50'],isolated_cpu['cpu_p50'])
        summary['strongest_cpu_p95']=min(summary['cpu_p95'],isolated_cpu['cpu_p95'])
        summary['speedup_against_strongest_cpu']=summary['strongest_cpu_p50']/summary['fpga_p50']
        summary['meets_50_percent']=bool(summary['fpga_p50']<=.5*summary['strongest_cpu_p50'] and summary['fpga_p95']<summary['strongest_cpu_p95'])''')
confirm=confirm.replace("'policy_screen_sha256':sha(a.policy)","'policy_screen_sha256':sha(a.policy),'isolated_cpu_confirmation_sha256':sha(isolated_path)")
save(f'software/latency/confirm_{new}_latency.py',confirm)
watcher=(ROOT/f'scripts/qualify_{old}.py').read_text()
start=watcher.index('deadline=time.monotonic()')
end=watcher.index("download('reports/fused/branch512_more_pool_oracle.json')",start)
watcher=watcher[:start]+'''# Launched only after earlier jobs are confirmed terminal and CPU isolation finishes.
isolated=json.loads((ROOT/'reports/fused/branch512_ab166_cpu_isolated_confirmation.json').read_text())
assert isolated['complete'] and not isolated['fpga_session_loaded']
'''+watcher[end:]
start=watcher.index("p=physical('validate_")
end=watcher.index("physical('tune_",start)
watcher=watcher[:start]+watcher[end:]
watcher=watcher.replace(old,new).replace('FPGA-ASR-DSP-input-register-vector-maskfast-confirmed-2026-10-14',
                                        'FPGA-ASR-IRQ-expanded-confirmed-2026-10-15')
watcher=watcher.replace("download('reports/fused/branch512_ab166_irq*.onnx')", "# Model graph unchanged; its qualified parent ONNX is preserved.")
save(f'scripts/qualify_{new}.py',watcher)
print('Prepared 24 IRQ placement policies and conservative isolated/paired CPU acceptance gate')
