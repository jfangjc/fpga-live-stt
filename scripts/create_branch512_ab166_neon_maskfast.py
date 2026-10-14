"""Preserve scalar experiments and combine independently proven exact optimizations."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
old = 'branch512_ab166_maskfast'
new = 'branch512_ab166_neon_maskfast'
sources = [ROOT/'software/latency'/f'{old}_benchmark.py']
sources += [ROOT/'software/latency'/f'{prefix}{old}_{suffix}.py'
            for prefix, suffix in [('validate_', 'physical'), ('tune_', 'policy'), ('confirm_', 'latency')]]
for source in sources:
    content = source.read_text().replace(old, new)
    if source.name.endswith('_benchmark.py'):
        content = content.replace('branch512_ab166_more_benchmark', 'branch512_ab166_neon_benchmark')
        content = content.replace('Use exact maskfast tails', 'Combine vector FPGA output unpacking and exact maskfast tails')
    ast.parse(content)
    destination = source.with_name(source.name.replace(old, new))
    if destination.exists():
        assert destination.read_text() == content, destination
    else:
        destination.write_text(content, newline='\n')

source = ROOT/'scripts/qualify_branch512_ab166_maskfast.py'
content = source.read_text()
start = content.index('deadline=time.monotonic()')
end = content.index("download('reports/fused/branch512_more_pool_oracle.json')", start)
wait = '''deadline=time.monotonic()+8*3600
# Wait for the existing scalar maskfast job; never overlap board measurements.
while True:
    path=ROOT/'reports/fused/branch512_ab166_maskfast_latency_confirmation.json'
    try:
        preceding=json.loads(path.read_text())
        if preceding['complete'] and preceding['hardware_execution']:break
    except (FileNotFoundError,json.JSONDecodeError,PermissionError):pass
    error=ROOT/'build/branch512_ab166_maskfast_qualification_error.log'
    if error.exists() and 'Traceback (most recent call last)' in read_log(error):
        raise RuntimeError('Scalar maskfast qualification failed; combined board tests not started')
    if time.monotonic()>deadline:raise TimeoutError('Preceding board qualification incomplete')
    time.sleep(5)
cpu=json.loads((ROOT/'reports/fused/branch512_ab166_cpu_policy_wide.json').read_text())
assert cpu['complete'] and cpu['candidate_count']==64 and cpu['all_warm_logits_bit_exact']
'''
content = (content[:start] + wait + content[end:]).replace(old, new)
# The preceding report in the wait must remain the scalar job's report.
content = content.replace("path=ROOT/'reports/fused/branch512_ab166_neon_maskfast_latency_confirmation.json'",
                          "path=ROOT/'reports/fused/branch512_ab166_maskfast_latency_confirmation.json'")
content = content.replace("error=ROOT/'build/branch512_ab166_neon_maskfast_qualification_error.log'",
                          "error=ROOT/'build/branch512_ab166_maskfast_qualification_error.log'")
content = content.replace('FPGA-ASR-DSP-input-register-maskfast-confirmed-2026-10-13',
                          'FPGA-ASR-DSP-input-register-vector-maskfast-confirmed-2026-10-14')
ast.parse(content)
destination = source.with_name('qualify_'+new+'.py')
if destination.exists():
    assert destination.read_text() == content
else:
    destination.write_text(content, newline='\n')
print('Prepared separate combined vector/maskfast qualification with sequential board execution')
