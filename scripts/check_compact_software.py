"""Verify compact primitive evidence before an isolated hardware experiment."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
exec((ROOT/'scripts/check_adaptive_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_adaptive_software.py')})
p=json.loads((ROOT/'reports/fused/compact_requant_evidence.json').read_text())
assert p['complete'] and p['rtl_lanes']==9600 and p['random_cases']==1000000
for name,value in p['sources_and_evidence_sha256'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value,name
print('PASS: source-bound compact primitive gate; full block qualification is separate')
