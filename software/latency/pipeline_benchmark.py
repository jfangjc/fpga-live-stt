"""Software overlap variant, bound to the independently qualified chain image."""
import ctypes,json,sys
from pathlib import Path
from chain_benchmark import *
from chain_benchmark import artifacts as parent_artifacts,bindings as parent_bindings,AudioTimer as ParentTimer
sys.path.insert(0,str(ROOT/'software/ort_fpga_pipeline'))
from pipeline_graph import fuse_residuals

class OverlapProfile(ctypes.Structure):
    _fields_=[('calls',ctypes.c_uint64)]+[(key,ctypes.c_double) for key in ('residual_seconds','device_seconds','join_seconds','total_seconds')]
def overlap_stats(lib):
    profile=OverlapProfile();lib.fpga_overlap_stats(ctypes.byref(profile));return {key:getattr(profile,key) for key,_ in profile._fields_}
def artifacts():
    items=parent_artifacts();items['parent_library']=items['library']
    items['fpga'],records=fuse_residuals(items['fpga']);items['oracle'],oracle_records=fuse_residuals(items['oracle'])
    items['overlap_records']=records;items['library']=ROOT/'software/ort_fpga_pipeline/libort_fpga.so'
    proof=json.loads((ROOT/'reports/fused/pipeline_native_oracle.json').read_text())
    assert proof['complete'] and proof['all_outputs_bit_exact'] and len(proof['records'])==8
    assert proof['library_sha256']==sha(items['library']) and proof['parent_library_sha256']==sha(items['parent_library'])
    assert proof['compiler_sha256']==sha(ROOT/'software/ort_fpga_pipeline/pipeline_graph.py')
    assert proof['runtime_source_sha256']==sha(ROOT/'software/ort_fpga_pipeline/pointwise.cc')
    assert proof['transport_source_sha256']==sha(ROOT/'software/ort_fpga_pipeline/qnc_transport.c')
    base_proof=json.loads((ROOT/'reports/fused/overlap_native_oracle.json').read_text())
    assert base_proof['complete'] and base_proof['compiler_sha256']==sha(ROOT/'software/ort_fpga_overlap/overlap_graph.py')
    assert sha(ROOT/'software/ort_fpga_pipeline/qnc_transport.c')==sha(ROOT/'software/ort_fpga_chain/qnc_transport.c')
    return items
def bindings(items):
    return parent_bindings(items)|{'parent_chain_library_sha256':sha(items['parent_library']),
                                   'overlap_graph_sha256':sha(ROOT/'software/ort_fpga_pipeline/pipeline_graph.py'),
                                   'overlap_runtime_source_sha256':sha(ROOT/'software/ort_fpga_pipeline/pointwise.cc'),
                                   'overlap_timer_source_sha256':sha(__file__),'base_overlap_graph_sha256':sha(ROOT/'software/ort_fpga_overlap/overlap_graph.py'),
                                   'overlapped_residual_branches':8,'nested_cpu_sessions':8,'nested_cpu_threads':4}
class AudioTimer(ParentTimer):
    def call(self,runner,audio,kind):
        before=overlap_stats(self.lib);result,logits=super().call(runner,audio,kind)
        result['overlap_counters']={key:value-before[key] for key,value in overlap_stats(self.lib).items()}
        assert result['overlap_counters']['calls']==(0 if kind=='cpu' else 8)
        return result,logits
