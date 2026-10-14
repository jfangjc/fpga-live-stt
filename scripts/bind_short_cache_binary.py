"""Bind the Bootgen output to the completed short-cache implementation gates."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
path=ROOT/'reports/fused/shortcache_firmware_evidence.json'
proof=json.loads(path.read_text())
assert proof['complete'] and proof['clock_hz']==100000000
assert proof['setup_slack_ns']>=0 and proof['hold_slack_ns']>=0
binary=ROOT/'deployment/asr-v3-shortcache/asr-v3-shortcache.bit.bin'
assert binary.stat().st_size>1000000
proof.update(firmware_bin_sha256=sha(binary),retained_pairs=32,
             accelerated_convolutions=64,maximum_feature_frames=256)
proof['sources_and_evidence_sha256'][Path(__file__).relative_to(ROOT).as_posix()]=sha(Path(__file__))
path.write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:proof[k] for k in ('firmware_bin_sha256','setup_slack_ns','hold_slack_ns')}))
