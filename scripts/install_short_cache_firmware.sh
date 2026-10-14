#!/bin/sh
# Install the separately gated cache experiment; preserve the accepted app.
set -eu
test "$(id -u)" = 0
root=/home/ubuntu/prototype-v3-fused
cd "$root"
.venv/bin/python - <<'PY'
import hashlib,json
from pathlib import Path
p=json.loads(Path('reports/fused/shortcache_firmware_evidence.json').read_text())
assert p['complete'] and p['clock_hz']==100000000
assert p['setup_slack_ns']>=0 and p['hold_slack_ns']>=0
for name in ('software/ort_fpga_shortcache/libort_fpga.so','deployment/experimental-shortcache/qn_tile.ko',
             'deployment/asr-v3-shortcache/asr-v3-shortcache.dtbo','deployment/asr-v3-shortcache/shell.json'):
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==p['sources_and_evidence_sha256'][name]
assert hashlib.sha256(Path('deployment/asr-v3-shortcache/asr-v3-shortcache.bit.bin').read_bytes()).hexdigest()==p['firmware_bin_sha256']
PY
mkdir -p /lib/firmware/xilinx/asr-v3-shortcache
for name in asr-v3-shortcache.bit.bin asr-v3-shortcache.dtbo shell.json; do
    cp "deployment/asr-v3-shortcache/$name" "/lib/firmware/xilinx/asr-v3-shortcache/$name"
    cmp "deployment/asr-v3-shortcache/$name" "/lib/firmware/xilinx/asr-v3-shortcache/$name"
done
echo 'Separate gated asr-v3-shortcache application installed.'
