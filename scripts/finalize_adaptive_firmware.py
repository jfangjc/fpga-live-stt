"""Bind converted firmware and compiled overlay after the routed image gate."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];directory=ROOT/'deployment/asr-v3-adaptive'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
path=ROOT/'reports/fused/adaptive_firmware_evidence.json';proof=json.loads(path.read_text())
assert proof['complete'] and not proof['hardware_execution']
assert sha(directory/'asr-v3-adaptive.bit')==proof['sources_and_evidence_sha256']['build/adaptive_system_v2/Prototype_v3_adaptive.runs/impl_1/asr_v2_top.bit']
firmware=directory/'asr-v3-adaptive.bit.bin';overlay=directory/'asr-v3-adaptive.dtbo'
assert firmware.stat().st_size>1000000 and overlay.stat().st_size>1000
proof['firmware_bin_sha256']=sha(firmware);proof['overlay_sha256']=sha(overlay)
proof['shell_sha256']=sha(directory/'shell.json')
for p in (firmware,overlay,directory/'shell.json',directory/'asr-v3-adaptive.dts',directory/'boot.bif'):
    proof['sources_and_evidence_sha256'][p.relative_to(ROOT).as_posix()]=sha(p)
proof['deployment_conversion_complete']=True
path.write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: routed source, converted firmware and compiled overlay bound')
