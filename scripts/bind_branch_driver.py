"""Bind compiled driver sources and independent host-side validation logs."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];reports=ROOT/'reports/fused'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
paths=[]
for name,marker in (('branch_driver_packet_checks.log','PASS: 345600'),('branch_driver_registered_checks.log','PASS: 232130')):
    p=reports/name;assert marker in p.read_text();paths.append(p)
paths += [p for p in (ROOT/'deployment/experimental-stream-branch').glob('*') if p.suffix in ('.c','.h','.ko')]
paths += [ROOT/'deployment/experimental-stream-branch/Makefile',reports/'branch_driver_build.log',Path(__file__)]
proof={'complete':True,'hardware_execution':False,'packet_checks':345600,'registered_range_checks':232130,
       'kernel':'6.8.0-1036-xilinx','sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}}
(reports/'branch_driver_validation.json').write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: isolated compiled branch driver and 577730 host-side checks bound')
