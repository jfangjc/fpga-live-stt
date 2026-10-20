"""Use exact maskfast tails on hybrid and the fastest screened CPU policy."""
from branch512_dma128166_more_benchmark import *
from branch512_dma128166_more_benchmark import artifacts as parent_artifacts,bindings as parent_bindings
from chain_benchmark import make_session as raw_session

def artifacts():
    items=parent_artifacts()
    path=ROOT/'reports/fused/residual_tail_maskfast_validation.json'
    proof=json.loads(path.read_text())
    assert proof['complete'] and proof['all_bit_exact'] and len(proof['micro_cases'])==567 and len(proof['full_model_cases'])==36
    library=ROOT/'software/latency/libresidual_tail_maskfast.so'
    assert sha(library)==proof['library_sha256']
    assert sha(ROOT/'software/latency/residual_tail_maskfast.cc')==proof['implementation_sha256']
    assert sha(ROOT/'software/latency/residual_tail.py')==proof['transform_sha256']
    assert sha(ROOT/'software/latency/test_residual_tail_maskfast.py')==proof['source_sha256']
    assert sha(items['model'])==proof['cpu_model_sha256']
    items['maskfast_library']=library;items['maskfast_validation']=path
    return items

def make_session(graph,config,libraries=()):
    libraries=list(libraries)
    if any(n.domain=='prototype.cpu.se_pool' for n in graph.graph.node):libraries.append(ROOT/'software/latency/libse_pool.so')
    if any(n.domain=='prototype.cpu.residual' for n in graph.graph.node):
        implementation=config.get('tail_impl','maskfast')
        assert implementation in ('original','maskfast')
        libraries.append(ROOT/'software/latency'/('libresidual_tail_maskfast.so' if implementation=='maskfast' else 'libresidual_tail.so'))
    return raw_session(graph,config,libraries)

def bindings(items):
    return parent_bindings(items)|{
        'residual_tail_original_library_sha256':sha(ROOT/'software/latency/libresidual_tail.so'),
        'residual_tail_library_sha256':sha(items['maskfast_library']),
        'maskfast_validation_sha256':sha(items['maskfast_validation']),
        'maskfast_runtime_source_sha256':sha(ROOT/'software/latency/residual_tail_maskfast.cc'),
        'timer_source_sha256':sha(__file__)}
