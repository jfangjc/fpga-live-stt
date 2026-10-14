"""Check frozen sources, arithmetic simulation and preserved physical parent."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
freeze=json.loads((ROOT/'reports/fused/shortwide_source_freeze.json').read_text())
for name,digest in freeze['sources_sha256'].items():assert sha(ROOT/name)==digest,name
parent=json.loads((ROOT/'reports/fused/shortcache_physical_validation.json').read_text())
assert sha(ROOT/'reports/fused/shortcache_physical_validation.json')==freeze['parent_physical_validation_sha256']
for name,key in [('software/ort_fpga_shortcache/libort_fpga.so','library_sha256'),('deployment/experimental-shortcache/qn_tile.ko','driver_sha256'),('deployment/asr-v3-shortcache/asr-v3-shortcache.bit.bin','firmware_sha256')]:assert sha(ROOT/name)==parent[key]
assert re.search(r'PASS: 64 short-cache retained pair arithmetic',(ROOT/'reports/fused/short_wide_sim.log').read_text())
print('PASS: wide arithmetic simulation, frozen source identities and protected physical parent')
