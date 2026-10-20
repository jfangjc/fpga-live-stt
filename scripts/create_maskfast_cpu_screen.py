"""Re-screen strongest CPU using both preserved and exact maskfast tails."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'software/latency/tune_se_pool_cpu.py').read_text()
text=text.replace('from tail_benchmark import *','from tail_benchmark import *\nfrom chain_benchmark import make_session as raw_session')
text=text.replace("pool_library=ROOT/'software/latency/libse_pool.so'", '''maskfast_library=ROOT/'software/latency/libresidual_tail_maskfast.so'
maskfast_proof=json.loads((ROOT/'reports/fused/residual_tail_maskfast_validation.json').read_text())
assert maskfast_proof['complete'] and maskfast_proof['all_bit_exact'] and len(maskfast_proof['full_model_cases'])==36
assert sha(maskfast_library)==maskfast_proof['library_sha256']
assert sha(ROOT/'software/latency/residual_tail_maskfast.cc')==maskfast_proof['implementation_sha256']
pool_library=ROOT/'software/latency/libse_pool.so' ''')
text=text.replace('frontend=Frontend(',"policies=[dict(c,tail_impl=impl) for c in policies for impl in ('original','maskfast')]\nfrontend=Frontend(")
old="runners=[make_session(pool_graph if c['graph']=='pool' else tail_graph,c,[ROOT/'software/latency/libboundary_lut.so']+([pool_library] if c['graph']=='pool' else [])) for c in policies]"
new="runners=[raw_session(pool_graph if c['graph']=='pool' else tail_graph,c,[ROOT/'software/latency/libboundary_lut.so',maskfast_library if c['tail_impl']=='maskfast' else lib]+([pool_library] if c['graph']=='pool' else [])) for c in policies]"
assert old in text;text=text.replace(old,new)
text=text.replace("'residual_tail_library_sha256':sha(lib)", "'residual_tail_library_sha256':sha(lib),'maskfast_library_sha256':sha(maskfast_library),'maskfast_validation_sha256':sha(ROOT/'reports/fused/residual_tail_maskfast_validation.json')")
dest=ROOT/'software/latency/tune_maskfast_cpu.py'
if dest.exists():assert dest.read_text()==text
else:dest.write_text(text,newline='\n')
print('Prepared sixteen CPU policies across original/maskfast and tail/pool graphs')
