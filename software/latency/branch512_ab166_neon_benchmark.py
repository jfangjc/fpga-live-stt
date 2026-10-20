"""Same hardware/graphs with independently validated vector output unpacking."""
import json
from pathlib import Path
from branch512_ab166_more_benchmark import *
from branch512_ab166_more_benchmark import artifacts as parent_artifacts,bindings as parent_bindings

def artifacts():
    p=json.loads((ROOT/'reports/fused/branch512_neon_evidence.json').read_text())
    assert p['complete'] and p['guarded_byte_cases']==1024 and p['packet_checks']==288
    for name,value in p['sources_sha256'].items():assert sha(ROOT/name)==value,name
    items=parent_artifacts()
    items['library']=ROOT/'software/ort_fpga_stream_branch512_neon/libort_fpga.so'
    assert sha(items['library'])==p['library_sha256']
    return items

def bindings(items):
    return parent_bindings(items)|{'vector_output_unpacking':True,
        'neon_transport_source_sha256':sha(ROOT/'software/ort_fpga_stream_branch512_neon/qnc_transport.c'),
        'neon_evidence_sha256':sha(ROOT/'reports/fused/branch512_neon_evidence.json')}
