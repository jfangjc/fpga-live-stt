#!/bin/sh
# Gated chain firmware activation with a kernel-compatible bulk rollback.
set -eu
root=/home/ubuntu/prototype-v3-fused
cd "$root"
test "$(id -u)" = 0
kernel=$(uname -r)
label=$(basename "$1" .py)
before="reports/fused/branch512_pipe166_bulk_before_$label.json"
restoration="reports/fused/branch512_pipe166_bulk_restored_$label.json"
.venv/bin/python scripts/verify_chain_restoration.py --capture --before "$before"
.venv/bin/python - <<'PY'
import hashlib,json
from pathlib import Path
p=json.loads(Path('reports/fused/branch512_pipe166_firmware_evidence.json').read_text())
assert p['complete'] and p['setup_slack_ns']>=0 and p['hold_slack_ns']>=0
for name in ('software/ort_fpga_stream_branch512/libort_fpga.so','software/latency/libboundary_lut.so','deployment/experimental-stream-branch/qn_tile.ko'):
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==p['sources_and_evidence_sha256'][name]
assert hashlib.sha256(Path('/lib/firmware/xilinx/asr-v3-branch512-pipe166/asr-v3-branch512-pipe166.bit.bin').read_bytes()).hexdigest()==p['firmware_bin_sha256']
PY
restore() {
    trap - EXIT
    rmmod qn_tile 2>/dev/null || true
    xmutil unloadapp || true
    xmutil loadapp asr-v3-bulk
    echo 100000000 > /sys/bus/platform/devices/asr-v3-bulk-clock/set_rate
    insmod "$root/deployment/kernel-compat/$kernel/bulk/qn_tile.ko"
    test -c /dev/qn-tile
    .venv/bin/python scripts/verify_chain_restoration.py --before "$before" --out "$restoration"
}
trap restore EXIT
rmmod qn_tile 2>/dev/null || true
xmutil unloadapp
xmutil loadapp asr-v3-branch512-pipe166
echo 166666666 > /sys/bus/platform/devices/asr-v3-branch512-pipe166-clock/set_rate
insmod "$root/deployment/experimental-stream-branch/qn_tile.ko"
test "$(cat /sys/module/qn_tile/parameters/residual_branch_protocol)" = 1
test -c /dev/qn-tile
test "$(cat /sys/class/fpga_manager/fpga0/state)" = operating
.venv/bin/python "$@"
restore
