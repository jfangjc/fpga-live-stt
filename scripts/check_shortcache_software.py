"""Check the selected graph's numerical gate and protect the measured parent."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
r=ROOT/'reports/fused';runtime=ROOT/'software/ort_fpga_shortcache'
p=read(r/'shortcache_native_oracle_validation.json')
assert p['complete'] and not p['hardware_execution'] and p['retained_pairs']==32
assert p['all_prefix_transcripts_exact'] and p['diagnostic_wer_delta_percentage_points']<=1
assert p['source_sha256']==sha(runtime/'validate.py')
assert p['graph_source_sha256']==sha(runtime/'graph.py')
assert p['selection_sha256']==sha(runtime/'selection.json')
assert p['library_sha256']==sha(runtime/'libort_fpga.so')
selection=read(runtime/'selection.json')
assert selection==read(r/'shortcache_selection_screen.json')
assert selection['complete'] and len(selection['selected'])==32 and selection['diagnostic_prefixes']==36
assert selection['source_sha256']==sha(runtime/'screen_pairs.py')
assert selection['graph_source_sha256']==sha(r/'shortcache_selection_graph_source.py')
assert selection['model_sha256']==p['model_sha256'] and selection['library_sha256']==p['library_sha256']
s=read(r/'shortcache_native_synthetic.json')
assert s['complete'] and s['exact_numpy_parity'] and s['library_sha256']==p['library_sha256']
assert s['source_sha256']==sha(runtime/'smoke.py')
parent=read(r/'cache_physical_validation.json')
for name,key in [('software/ort_fpga_cache/libort_fpga.so','library_sha256'),
                 ('deployment/experimental-cache/qn_tile.ko','driver_sha256'),
                 ('deployment/asr-v3-cache/asr-v3-cache.bit.bin','firmware_sha256')]:
    assert sha(ROOT/name)==parent[key]
assert 'PASS: 62144 short-cache packet' in (r/'shortcache_driver_protocol.log').read_text()
assert 'PASS: 32-slot transport residency' in (r/'shortcache_transport.log').read_text()
print('PASS: selected graph accuracy, kernel arithmetic, protocol, residency and protected parent gates')
