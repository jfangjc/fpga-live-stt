"""Bind exact tail candidates; record the slower vector experiment as rejected."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
paths=[];candidates=[]
for kind in ('vector','maskfast'):
    validation=ROOT/f'reports/fused/residual_tail_{kind}_validation.json'
    benchmark=ROOT/f'reports/fused/residual_tail_{kind}_operator_benchmark.json'
    p=json.loads(validation.read_text());b=json.loads(benchmark.read_text())
    library=ROOT/f'software/latency/libresidual_tail_{kind}.so'
    source=ROOT/f'software/latency/residual_tail_{kind}.cc'
    test=ROOT/f'software/latency/test_residual_tail_{kind}.py'
    timer=ROOT/f'software/latency/benchmark_residual_tail_{kind}.py'
    assert p['complete'] and p['all_bit_exact'] and len(p['micro_cases'])==567 and len(p['full_model_cases'])==36
    assert not p['hardware_execution']
    for path,key in ((library,'library_sha256'),(source,'implementation_sha256'),(test,'source_sha256'),(ROOT/'software/latency/residual_tail.py','transform_sha256')):
        assert sha(path)==p[key],path
    assert b['complete'] and b['all_outputs_bit_exact'] and len(b['cases'])==105 and b['runs_per_case']==100
    assert b['vector_library_sha256']==sha(library) and b['source_sha256']==sha(timer)
    assert b['validation_sha256']==sha(validation)
    assert b['original_library_sha256']==sha(ROOT/'software/latency/libresidual_tail.so')
    faster=sum(r['reduction_percent']>0 for r in b['cases'])
    assert faster==(105 if kind=='maskfast' else 0)
    candidates.append({'name':kind,'operator_cases':105,'faster_cases':faster,
                       'status':'Full-path candidate; independent CPU/hybrid confirmation pending' if kind=='maskfast' else 'Rejected: slower in every paired operator case',
                       'full_path_gain_proven':False})
    paths += [validation,benchmark,library,source,test,timer,ROOT/f'scripts/create_residual_tail_{kind}.py']
paths += [ROOT/'software/latency/residual_tail.cc',ROOT/'software/latency/residual_tail.py',ROOT/'software/latency/libresidual_tail.so',Path(__file__)]
proof={'complete':True,'hardware_execution':False,'timing_acceptance':False,'candidates':candidates,
       'sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}}
(ROOT/'reports/fused/residual_tail_candidates_evidence.json').write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: 567 + 36 exactness cases per variant; maskfast 105/105 faster, vector 0/105 faster')
