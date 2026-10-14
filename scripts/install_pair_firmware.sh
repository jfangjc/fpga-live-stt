#!/bin/sh
# Install the gated experimental application without replacing accepted bulk.
set -eu
test "$(id -u)" = 0
root=/home/ubuntu/prototype-v3-fused
cd "$root"
echo '7453ffbf4f5c652c432acf39246c9e38fe2f170710a89599bbccbed7efd3094e  deployment/asr-v3-pair/asr-v3-pair.bit.bin' | sha256sum -c -
.venv/bin/python - <<'PY'
import hashlib,json
from pathlib import Path
p=json.loads(Path('reports/fused/pair_firmware_evidence.json').read_text())
assert p['complete'] and p['clock_hz']==100000000
assert p['setup_slack_ns']>=0 and p['hold_slack_ns']>=0
for name in ('software/ort_fpga_pair/libort_fpga.so','deployment/experimental-pair/qn_tile.ko'):
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==p['sources_and_evidence_sha256'][name]
PY
mkdir -p /lib/firmware/xilinx/asr-v3-pair
for name in asr-v3-pair.bit.bin asr-v3-pair.dtbo shell.json; do
    cp "deployment/asr-v3-pair/$name" "/lib/firmware/xilinx/asr-v3-pair/$name"
    cmp "deployment/asr-v3-pair/$name" "/lib/firmware/xilinx/asr-v3-pair/$name"
done
echo 'Separate gated asr-v3-pair application installed.'
