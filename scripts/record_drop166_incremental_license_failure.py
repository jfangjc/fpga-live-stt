"""Preserve actual license rejection; the full implementation fallback is separate."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
paths=[ROOT/'reports/fused/branch512_drop166_incremental_license_driver.log',
       ROOT/'reports/fused/branch512_drop166_incremental_license_run.log',Path(__file__)]
for path in paths[:2]:
    data=path.read_bytes()
    log=data.decode('utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8')
    assert 'ERROR: [Vivado 12-29181]' in log and '"BASIC"' in log
    assert 'read_checkpoint -directive TimingClosure -incremental' in log
proof={'complete':True,'hardware_execution':False,'deployment_started':False,
       'incremental_license_supported':False,'fallback':'Full implementation of unchanged synthesized RTL',
       'sources_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
dest=ROOT/'reports/fused/branch512_drop166_incremental_license_failure.json'
if dest.exists():assert json.loads(dest.read_text())==proof
else:dest.write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: actual incremental-license rejection preserved; no physical deployment')
