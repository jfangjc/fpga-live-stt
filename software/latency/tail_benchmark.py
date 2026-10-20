"""Common exact CPU-tail fusion on both sides of a retained-chain comparison."""
import json
from chain_benchmark import *
from chain_benchmark import artifacts as parent_artifacts,bindings as parent_bindings,make_session as base_session
from residual_tail import transform as tails

def artifacts():
    items=parent_artifacts();proof=json.loads((ROOT/'reports/fused/residual_tail_validation.json').read_text())
    items['boundary_cpu']=items['cpu']
    assert proof['complete'] and proof['all_bit_exact'] and len(proof['full_model_cases'])==36
    items['tail_library']=ROOT/'software/latency/libresidual_tail.so'
    assert sha(items['tail_library'])==proof['library_sha256']
    assert sha(ROOT/'software/latency/residual_tail.cc')==proof['implementation_sha256']
    assert sha(ROOT/'software/latency/residual_tail.py')==proof['transform_sha256']
    for kind in ('cpu','fpga','oracle'):
        items[kind],records=tails(items[kind]);assert len(records)==len(proof['records'])
    items['tail_records']=records
    return items

def make_session(graph,config,libraries=()):
    libraries=list(libraries)
    if any(n.domain=='prototype.cpu.residual' for n in graph.graph.node):
        libraries.append(ROOT/'software/latency/libresidual_tail.so')
    return base_session(graph,config,libraries)

def bindings(items):
    return parent_bindings(items)|{'residual_tail_library_sha256':sha(items['tail_library']),
                                  'residual_tail_transform_sha256':sha(ROOT/'software/latency/residual_tail.py'),
                                  'residual_tail_runtime_sha256':sha(ROOT/'software/latency/residual_tail.cc'),
                                  'fused_cpu_residual_tails':len(items['tail_records']),
                                  'tail_timer_source_sha256':sha(__file__)}

def cpu_graph(items,config):
    return items['boundary_cpu'] if config.get('graph')=='boundary' else items['cpu']
