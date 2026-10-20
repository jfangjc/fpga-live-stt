"""Require source-bound original arithmetic and retimed vendor/protocol gates."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
exec((ROOT/'scripts/check_branch512_guard_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_branch512_guard_software.py')})
p=json.loads((ROOT/'reports/fused/branch512_ab_regression_evidence.json').read_text())
assert p['complete'] and p['controller_and_arithmetic_unchanged']
assert p['vendor_old_new_model_checks']==203980 and p['exhaustive_signed_byte_products']==65536
assert p['mac_latency_cycles']==2 and p['full_blocks_checked']==25 and p['full_reset_replay_cases']==8
for name,value in p['sources_sha256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value,name
print('PASS: source-bound exact DSP input-register retiming')
