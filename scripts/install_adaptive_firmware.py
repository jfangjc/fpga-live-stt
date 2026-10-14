"""Install the isolated chain app after checking the complete artifact proof."""
import hashlib,json,os,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];assert os.geteuid()==0
proof=json.loads((ROOT/'reports/fused/adaptive_firmware_evidence.json').read_text())
assert proof['complete'] and proof['deployment_conversion_complete']
source=ROOT/'deployment/asr-v3-adaptive';destination=Path('/lib/firmware/xilinx/asr-v3-adaptive')
assert not destination.exists(),'Refusing to overwrite an existing FPGA app'
for name,key in (('asr-v3-adaptive.bit.bin','firmware_bin_sha256'),('asr-v3-adaptive.dtbo','overlay_sha256'),('shell.json','shell_sha256')):
    assert hashlib.sha256((source/name).read_bytes()).hexdigest()==proof[key]
shutil.copytree(source,destination,ignore=shutil.ignore_patterns('*.bit','*.xsa','*.dts','*.bif'))
print('Installed verified separate app:',destination)
