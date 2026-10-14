"""Exercise the actual confirmation loop's intermittent-logit corruption gate."""
import ast,hashlib,json,random
from pathlib import Path
from types import SimpleNamespace
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'software/latency/confirm_branch512_outslice166_maskfast_latency.py'
tree=ast.parse(source.read_text())
loop=next(n for n in ast.walk(tree) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='iteration')
code=compile(ast.Module(body=[loop],type_ignores=[]),str(source),'exec')
expected=np.array([[[0.25,0.5,0.75]]],np.float32)
class Timer:
    def __init__(self,corrupt):self.corrupt=corrupt;self.calls=0
    def call(self,runner,clip,kind):
        pair=self.calls//2;self.calls+=1;output=expected.copy()
        if self.corrupt and pair==1 and kind=='fpga':output[0,0,1]=np.nextafter(output[0,0,1],np.float32(1))
        return {'text':'unchanged','length':1,'counters':{'loads':256 if kind=='fpga' else 0,'ioctls':24 if kind=='fpga' else 0}},output
def run(corrupt):
    scope={'np':np,'rng':random.Random(20261013),'time':SimpleNamespace(sleep=lambda _:None),
           'a':SimpleNamespace(runs=3),'timer':Timer(corrupt),'cpu':object(),'fpga':object(),
           'clip':None,'cold':{'text':'unchanged'},'actual':expected,'rows':[]}
    exec(code,scope);return scope['rows']
rows=run(False);assert len(rows)==3 and all(r['all_logits_bit_exact'] for r in rows)
try:run(True)
except AssertionError:pass
else:raise AssertionError('One-ULP corruption escaped while text/length/counters were unchanged')
report={'complete':True,'hardware_execution':False,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'test_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'exact_pairs_accepted':3,
        'intermittent_one_ulp_corruption_rejected':True,'text_and_lengths_unchanged_in_negative_case':True,
        'scope':'Actual warm confirmation loop with synthetic outputs; not physical or latency evidence'}
(ROOT/'reports/fused/warm_logit_gate_validation.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS: exact warm pairs accepted; intermittent one-ULP output error rejected')
