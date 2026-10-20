#!/bin/sh
# Install the separately gated cache experiment; preserve the accepted app.
set -eu
test "$(id -u)" = 0
root=/home/ubuntu/prototype-v3-fused
cd "$root"
.venv/bin/python - <<'PY'
import hashlib,json
from pathlib import Path
p=json.loads(Path('reports/fused/cache_firmware_evidence.json').read_text())
assert p['complete'] and p['clock_hz']==100000000
assert p['setup_slack_ns']>=0 and p['hold_slack_ns']>=0
for name in ('software/ort_fpga_cache/libort_fpga.so','deployment/experimental-cache/qn_tile.ko'):
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==p['sources_and_evidence_sha256'][name]
assert hashlib.sha256(Path('deployment/asr-v3-cache/asr-v3-cache.bit.bin').read_bytes()).hexdigest()==p['firmware_bin_sha256']
PY
mkdir -p /lib/firmware/xilinx/asr-v3-cache
for name in asr-v3-cache.bit.bin asr-v3-cache.dtbo shell.json; do
    cp "deployment/asr-v3-cache/$name" "/lib/firmware/xilinx/asr-v3-cache/$name"
    cmp "deployment/asr-v3-cache/$name" "/lib/firmware/xilinx/asr-v3-cache/$name"
done
echo 'Separate gated asr-v3-cache application installed.'
