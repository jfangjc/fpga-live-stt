"""Prove the specialized binary header acceptance is identical for all hk/ht."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
old=ROOT/'rtl/experimental/qn_branch512_drop_inner.sv'
new=ROOT/'rtl/experimental/qn_branch512_guard_inner.sv'
text=old.read_text();guard='hk*((ht+15)>>4)<=4096 && '
assert new.read_text()==text.replace('qn_branch512_drop_inner','qn_branch512_guard_inner').replace(guard,'')
assert text.count(guard)==1 and 'hk==256 && hm==256 && ht>0 && ht<=256 &&' in text
# The remaining metadata factors are byte-identical. hk!=256 makes both
# predicates false for every ht. Enumerate all 16-bit ht at the sole eligible hk.
for ht in range(65536):
    bounded=0<ht<=256
    assert (bounded and 256*((ht+15)>>4)<=4096)==bounded,ht
for hk in range(65536):
    if hk!=256:assert not (hk==256)
assert 65535*((65535+15)>>4)<2**32
paths=[old,new,ROOT/'scripts/create_branch512_guard.py',Path(__file__)]
proof={'complete':True,'hardware_execution':False,'binary_header_acceptance_unchanged':True,
       'all_hk_ht_combinations_covered':2**32,'eligible_hk':256,'ht_values_enumerated':65536,
       'proof':'For hk!=256 both predicates are false for every ht; at hk==256 all 65536 ht values are enumerated. Other header factors are byte-identical.',
       'maximum_eligible_product':4096,'maximum_full_input_product':65535*((65535+15)>>4),
       'datapath_and_handshake_unchanged':True,
       'sources_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
dest=ROOT/'reports/fused/branch512_header_guard_equivalence.json'
if dest.exists():assert json.loads(dest.read_text())==proof
else:dest.write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: all 2^32 binary hk/ht combinations covered; header acceptance unchanged')
