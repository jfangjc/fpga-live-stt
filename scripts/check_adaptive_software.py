"""Require CPU-exact arithmetic and a source-bound adaptive unit regression."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
exec((ROOT/'scripts/check_stream_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_stream_software.py')})
proof=json.loads((ROOT/'reports/fused/adaptive_unit_validation.json').read_text())
assert proof['complete'] and proof['cases']==135 and not proof['hardware_execution']
for name,value in proof['sources_and_evidence_sha256'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value,name
print('PASS: source-bound 135-case adaptive schedule arithmetic gate')
