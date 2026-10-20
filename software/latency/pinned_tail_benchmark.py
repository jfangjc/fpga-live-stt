"""Pinned residual overlap combined with the common exact tail optimization."""
from tail_benchmark import *
from tail_benchmark import artifacts as tail_artifacts,bindings as tail_bindings,make_session as tail_session
import pinned_benchmark as pinned
from pinned_benchmark import AudioTimer,overlap_stats,OverlapProfile

def artifacts():
    items=tail_artifacts();items['parent_library']=items['library']
    items['fpga'],records=pinned.fuse_residuals(items['fpga']);items['oracle'],_=pinned.fuse_residuals(items['oracle'])
    items['overlap_records']=records;items['library']=ROOT/'software/ort_fpga_pipeline_pinned/libort_fpga.so'
    proof=json.loads((ROOT/'reports/fused/pinned_native_oracle.json').read_text())
    assert proof['complete'] and proof['all_outputs_bit_exact'] and len(records)==8
    assert proof['library_sha256']==sha(items['library']) and proof['parent_library_sha256']==sha(items['parent_library'])
    assert proof['compiler_sha256']==sha(ROOT/'software/ort_fpga_pipeline_pinned/pinned_graph.py')
    assert proof['runtime_source_sha256']==sha(ROOT/'software/ort_fpga_pipeline_pinned/pointwise.cc')
    assert proof['transport_source_sha256']==sha(ROOT/'software/ort_fpga_pipeline_pinned/qnc_transport.c')
    base=json.loads((ROOT/'reports/fused/overlap_native_oracle.json').read_text());assert base['compiler_sha256']==sha(ROOT/'software/ort_fpga_overlap/overlap_graph.py')
    return items

def make_session(graph,config,libraries=()):
    libraries=list(libraries)
    if any(n.domain=='prototype.cpu.residual' for n in graph.graph.node):libraries.append(ROOT/'software/latency/libresidual_tail.so')
    return pinned.make_session(graph,config,libraries)

def bindings(items):
    return tail_bindings(items)|{'parent_chain_library_sha256':sha(items['parent_library']),
                                'overlap_graph_sha256':sha(ROOT/'software/ort_fpga_pipeline_pinned/pinned_graph.py'),
                                'overlap_runtime_source_sha256':sha(ROOT/'software/ort_fpga_pipeline_pinned/pointwise.cc'),
                                'base_overlap_graph_sha256':sha(ROOT/'software/ort_fpga_overlap/overlap_graph.py'),
                                'overlapped_residual_branches':8,'cpu_residual_worker_core':0,'pinned_tail_timer_source_sha256':sha(__file__)}
