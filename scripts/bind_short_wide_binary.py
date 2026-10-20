"""Bind the wider Bootgen image to completed implementation evidence."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'reports/fused/shortwide_firmware_evidence.json';p=json.loads(path.read_text())
assert p['complete'] and p['clock_hz']==100000000 and p['setup_slack_ns']>=0 and p['hold_slack_ns']>=0
binary=ROOT/'deployment/asr-v3-shortwide/asr-v3-shortwide.bit.bin';assert binary.stat().st_size>1000000
p['firmware_bin_sha256']=hashlib.sha256(binary.read_bytes()).hexdigest()
path.write_text(json.dumps(p,indent=2)+'\n');print(p['firmware_bin_sha256'])
