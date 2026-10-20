"""Prepare isolated DMA deployment and full conservative-baseline qualification."""
import ast
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
old, new = 'branch512_ab166', 'branch512_dma128166'

def convert(text):
    text = text.replace(old, new).replace('asr-v3-branch512-ab166', 'asr-v3-branch512-dma128166')
    # CPU model/policies are unchanged; use the already validated strongest baseline.
    text = text.replace(new+'_cpu_policy_wide', old+'_cpu_policy_wide')
    text = text.replace(new+'_cpu_isolated', old+'_cpu_isolated')
    return text

def save(path, text):
    destination = ROOT/path
    if destination.suffix == '.py': ast.parse(text)
    if destination.exists(): assert destination.read_text() == text, destination
    else: destination.write_text(text, newline='\n')

for suffix in ('benchmark', 'more_benchmark', 'neon_benchmark', 'maskfast_benchmark',
               'neon_maskfast_benchmark', 'irq_benchmark'):
    path = f'software/latency/{old}_{suffix}.py'
    save(path.replace(old, new), convert((ROOT/path).read_text()))
for prefix, suffix in [('test_', 'blocks'), ('tune_', 'irq_policy'), ('confirm_', 'irq_latency')]:
    path = f'software/latency/{prefix}{old}_{suffix}.py'
    save(path.replace(old, new), convert((ROOT/path).read_text()))
validation = convert((ROOT/f'software/latency/validate_{old}_neon_maskfast_physical.py').read_text())
validation = validation.replace(f'from {new}_neon_maskfast_benchmark import *', f'from {new}_irq_benchmark import *')
save(f'software/latency/validate_{new}_physical.py', validation)
for prefix in ('finalize_', 'install_'):
    path = f'scripts/{prefix}{old}_firmware.py'
    save(path.replace(old, new), convert((ROOT/path).read_text()))
path = f'scripts/run_{old}_board.sh'
save(path.replace(old, new), convert((ROOT/path).read_text()))

prepare = convert((ROOT/f'scripts/prepare_{old}_firmware.py').read_text())
anchor = "timing=json.loads((reports/'branch512_dma128166_system_implementation.json').read_text())"
assert anchor in prepare
configuration = '''# Require the exact intended change in the isolated DMA IP configuration.
parent_xci=ROOT/'build/branch512_ab166_system/Prototype_v3_branch512_ab166.srcs/sources_1/bd/asr_v2_system/ip/asr_v2_system_tensor_dma_0/asr_v2_system_tensor_dma_0.xci'
candidate_xci=ROOT/'build/branch512_dma128166_system/Prototype_v3_branch512_dma128166.srcs/sources_1/bd/asr_v2_system/ip/asr_v2_system_tensor_dma_0/asr_v2_system_tensor_dma_0.xci'
def component_values(path):
    parameters=json.loads(path.read_text())['ip_inst']['parameters']['component_parameters']
    return {k:[v['value'] for v in values] for k,values in parameters.items()}
before=component_values(parent_xci);after=component_values(candidate_xci)
changed={k for k in before.keys()|after.keys() if before.get(k)!=after.get(k)}
assert changed=={'c_mm2s_burst_size','c_s2mm_burst_size'},changed
for key in changed:assert before[key]==['16'] and after[key]==['128']
for key in ('c_m_axi_mm2s_data_width','c_m_axi_s2mm_data_width'):assert after[key]==['128']
preparation=reports/'branch512_dma128166_preparation.json'
prepared=json.loads(preparation.read_text());assert prepared['complete'] and prepared['preparation_only']
assert prepared['parent_dma_xci_sha256']==sha(parent_xci)
for name,value in prepared['sources_sha256'].items():assert sha(ROOT/name)==value,name
paths += [parent_xci,candidate_xci,preparation]+[ROOT/name for name in prepared['sources_sha256']]
paths += [ROOT/'reports/fused/branch512_neon_evidence.json']
paths += [p for p in (ROOT/'software/ort_fpga_stream_branch512_neon').glob('*') if p.is_file() and p.suffix in ('.c','.cc','.h','.so')]
'''
prepare = prepare.replace(anchor, configuration+'\n'+anchor)
prepare = prepare.replace('incremental_implementation=False,implementation_flow=',
                          "dma_max_burst_beats=128,dma_config_changes=sorted(changed),incremental_implementation=False,implementation_flow=")
save(f'scripts/prepare_{new}_firmware.py', prepare)

watch = convert((ROOT/f'scripts/qualify_{old}.py').read_text())
anchor = '    if time.monotonic()>deadline:raise TimeoutError('
index = watch.index(anchor)
watch = watch[:index]+'''    for name in ('branch512_dma128166_synth_driver.log','branch512_dma128166_build_error.log'):
        failure=ROOT/'build'/name
        if failure.exists() and (timing_failed(failure) or 'throw' in read_log(failure).lower() and 'failed' in read_log(failure).lower()):
            raise RuntimeError('DMA build failed; board deployment not started')
'''+watch[index:]
start = watch.index("physical('validate_")
end = watch.index("download('reports/fused/branch512_dma128166*.json'", start)
watch = watch[:start]+'''physical('validate_branch512_dma128166_physical.py','--out reports/fused/branch512_dma128166_physical_validation.json','branch512_dma128166_physical_validation')
parity=json.loads((ROOT/'reports/fused/branch512_dma128166_physical_validation.json').read_text())
assert len(parity['clips'])==36 and all(row['physical_oracle_bit_exact'] for row in parity['clips'])
physical('tune_branch512_dma128166_irq_policy.py','--runs 30 --out reports/fused/branch512_dma128166_irq_latency_policy.json','branch512_dma128166_irq_latency_policy')
physical('confirm_branch512_dma128166_irq_latency.py','--policy reports/fused/branch512_dma128166_irq_latency_policy.json --runs 300 --out reports/fused/branch512_dma128166_irq_latency_confirmation.json','branch512_dma128166_irq_latency_confirmation')
'''+watch[end:]
watch = watch.replace('branch512_dma128166_latency_confirmation.json', 'branch512_dma128166_irq_latency_confirmation.json')
watch += '''
local([PY,'-I','scripts/save_latency20_work.py','--destination',Path('C:/Users/jfang/Downloads/FPGA-ASR-DMA128-confirmed-2026-10-15'),'--result','reports/fused/branch512_dma128166_irq_latency_confirmation.json'])
'''
save(f'scripts/qualify_{new}.py', watch)
stage = convert((ROOT/'scripts/verify_branch512_ab166_stage.py').read_text())
save('scripts/verify_branch512_dma128166_stage.py', stage)
print('Prepared gated DMA deployment, 294 block tests, 36 model checks and 300-pair conservative confirmations')
