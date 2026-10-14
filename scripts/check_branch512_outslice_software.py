"""Require unchanged parent evidence and source-bound stream-slice regressions."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
exec((ROOT/'scripts/check_branch512_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_branch512_software.py')})
p=json.loads((ROOT/'reports/fused/branch512_outslice_regression_evidence.json').read_text())
assert p['complete'] and p['pipelined_cases']==25 and p['full_pipeline_reset_replay_cases']==6 and p['voice_axi_accesses']==77
assert p['output_data_reset_replay_cases']==2
for name,value in p['sources_sha256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value,name
print('PASS: isolated registered input/output boundaries and legacy-MAC-free inference image')
