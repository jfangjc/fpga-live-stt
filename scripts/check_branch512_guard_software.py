"""Require the unchanged parent datapath and new source-bound protocol proof."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
exec((ROOT/'scripts/check_branch512_drop_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_branch512_drop_software.py')})
p=json.loads((ROOT/'reports/fused/branch512_guard_regression_evidence.json').read_text())
assert p['complete'] and p['header_acceptance_unchanged'] and p['datapath_and_handshake_unchanged']
assert p['full_blocks_checked']==25 and p['full_reset_replay_cases']==8
for name,value in p['sources_sha256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value,name
print('PASS: source-bound exact specialized header simplification')
