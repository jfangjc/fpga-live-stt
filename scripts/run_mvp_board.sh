#!/bin/sh
# Run one physical inference/qualification job and verify bulk restoration.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
test "$(id -u)" = 0 || { echo 'Run with sudo sh scripts/run_mvp_board.sh ...' >&2; exit 1; }
test "$#" -gt 0 || { echo 'Expected a Python script and its arguments' >&2; exit 1; }
python="$root/.venv/bin/python"
kernel=$(uname -r)
driver="$root/deployment/experimental-stream-branch/qn_tile.ko"
rollback="$root/deployment/kernel-compat/$kernel/bulk/qn_tile.ko"
for module in "$driver" "$rollback"; do
    test -f "$module"
    test "$(modinfo -F vermagic "$module" | cut -d ' ' -f 1)" = "$kernel" || {
        echo "Kernel mismatch: $module" >&2; exit 1;
    }
done
"$python" scripts/verify_mvp.py --manifest release/MVP_MANIFEST.json
"$python" - <<'PY'
import hashlib, json
from pathlib import Path
for app in ('asr-v3-bulk', 'asr-v3-branch512-ab166'):
    local = Path('deployment') / app
    installed = Path('/lib/firmware/xilinx') / app
    for name in (app+'.bit.bin', app+'.dtbo', 'shell.json'):
        if hashlib.sha256((local/name).read_bytes()).digest() != hashlib.sha256((installed/name).read_bytes()).digest():
            raise RuntimeError('Installed firmware differs: '+str(installed/name))
PY
mkdir -p reports/mvp
stamp=$(date -u +%Y%m%dT%H%M%SZ)_$$
before="reports/mvp/bulk_before_$stamp.json"
restored="reports/mvp/bulk_restored_$stamp.json"
"$python" scripts/verify_chain_restoration.py --capture --before "$before"
restore() {
    status=$?
    trap - EXIT INT TERM
    # Any restoration failure must make the overall command fail.
    set -e
    if test -d /sys/module/qn_tile; then rmmod qn_tile; fi
    # A failed activation may leave no app loaded; load and verify bulk anyway.
    xmutil unloadapp || true
    xmutil loadapp asr-v3-bulk
    echo 100000000 > /sys/bus/platform/devices/asr-v3-bulk-clock/set_rate
    insmod "$rollback"
    "$python" scripts/verify_chain_restoration.py --before "$before" --out "$restored"
    exit "$status"
}
trap restore EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
rmmod qn_tile
xmutil unloadapp
xmutil loadapp asr-v3-branch512-ab166
echo 166666666 > /sys/bus/platform/devices/asr-v3-branch512-ab166-clock/set_rate
insmod "$driver"
test "$(cat /sys/module/qn_tile/parameters/residual_branch_protocol)" = 1
test -c /dev/qn-tile
test "$(cat /sys/class/fpga_manager/fpga0/state)" = operating
"$python" "$@"
