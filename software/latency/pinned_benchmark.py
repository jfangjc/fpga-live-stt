"""Software overlap variant, bound to the independently qualified chain image."""
import ctypes,json,sys
from pathlib import Path
from chain_benchmark import *
from chain_benchmark import artifacts as parent_artifacts,bindings as parent_bindings,AudioTimer as ParentTimer
sys.path.insert(0,str(ROOT/'software/ort_fpga_pipeline_pinned'))
from pinned_graph import fuse_residuals

class OverlapProfile(ctypes.Structure):
    _fields_=[('calls',ctypes.c_uint64)]+[(key,ctypes.c_double) for key in ('residual_seconds','device_seconds','join_seconds','total_seconds')]
def overlap_stats(lib):
    profile=OverlapProfile();lib.fpga_overlap_stats(ctypes.byref(profile));return {key:getattr(profile,key) for key,_ in profile._fields_}
def artifacts():
    items=parent_artifacts();items['parent_library']=items['library']
    items['fpga'],records=fuse_residuals(items['fpga']);items['oracle'],oracle_records=fuse_residuals(items['oracle'])
    items['overlap_records']=records;items['library']=ROOT/'software/ort_fpga_pipeline_pinned/libort_fpga.so'
    proof=json.loads((ROOT/'reports/fused/pinned_native_oracle.json').read_text())
    assert proof['complete'] and proof['all_outputs_bit_exact'] and len(proof['records'])==8
    assert proof['library_sha256']==sha(items['library']) and proof['parent_library_sha256']==sha(items['parent_library'])
    assert proof['compiler_sha256']==sha(ROOT/'software/ort_fpga_pipeline_pinned/pinned_graph.py')
    assert proof['runtime_source_sha256']==sha(ROOT/'software/ort_fpga_pipeline_pinned/pointwise.cc')
    assert proof['transport_source_sha256']==sha(ROOT/'software/ort_fpga_pipeline_pinned/qnc_transport.c')
    base_proof=json.loads((ROOT/'reports/fused/overlap_native_oracle.json').read_text())
    assert base_proof['complete'] and base_proof['compiler_sha256']==sha(ROOT/'software/ort_fpga_overlap/overlap_graph.py')
    assert sha(ROOT/'software/ort_fpga_pipeline_pinned/qnc_transport.c')==sha(ROOT/'software/ort_fpga_chain/qnc_transport.c')
    return items
def bindings(items):
    return parent_bindings(items)|{'parent_chain_library_sha256':sha(items['parent_library']),
                                   'overlap_graph_sha256':sha(ROOT/'software/ort_fpga_pipeline_pinned/pinned_graph.py'),
                                   'overlap_runtime_source_sha256':sha(ROOT/'software/ort_fpga_pipeline_pinned/pointwise.cc'),
                                   'overlap_timer_source_sha256':sha(__file__),'base_overlap_graph_sha256':sha(ROOT/'software/ort_fpga_overlap/overlap_graph.py'),
                                   'overlapped_residual_branches':8,'nested_cpu_sessions':8,'default_nested_cpu_threads':3,'cpu_residual_worker_core':0}
class AudioTimer(ParentTimer):
    def call(self,runner,audio,kind):
        before=overlap_stats(self.lib);result,logits=super().call(runner,audio,kind)
        result['overlap_counters']={key:value-before[key] for key,value in overlap_stats(self.lib).items()}
        assert result['overlap_counters']['calls']==(0 if kind=='cpu' else 8)
        return result,logits

from chain_benchmark import make_session as base_make_session
import copy
def make_session(graph,config,libraries=()):
    if any(n.domain=='prototype.fpga.pipeline.pinned' and n.op_type in ('FpgaResidualChain','OracleResidualChain') for n in graph.graph.node):
        graph=copy.deepcopy(graph)
        for node in graph.graph.node:
            if node.domain=='prototype.fpga.pipeline.pinned' and node.op_type in ('FpgaResidualChain','OracleResidualChain'):
                attrs=[a for a in node.attribute if a.name!='res_threads'];del node.attribute[:];node.attribute.extend(attrs)
                node.attribute.append(onnx.helper.make_attribute('res_threads',config.get('res_threads',3)))
    return base_make_session(graph,config,libraries)
