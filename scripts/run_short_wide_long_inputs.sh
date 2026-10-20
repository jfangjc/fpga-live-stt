#!/bin/sh
set -eu
root=/home/ubuntu/prototype-v3-fused
cd "$root"
restore_bulk() {
    trap - EXIT
    rmmod qn_tile 2>/dev/null || true
    xmutil unloadapp || true
    xmutil loadapp asr-v3-bulk
    echo 100000000 > /sys/bus/platform/devices/asr-v3-bulk-clock/set_rate
    insmod "$root/deployment/experimental-bulk/qn_tile.ko"
}
sh deployment/asr-v3-shortwide/activate.sh
trap restore_bulk EXIT
.venv/bin/python software/latency/test_short_wide_long_inputs.py --contexts 1.5 2 2.5 2.55 --runs 100 --out reports/fused/shortwide_long_inputs.json
restore_bulk
.venv/bin/python scripts/verify_short_wide_long_restoration.py
echo 'Longer-input benchmark finished; accepted bulk restored.'
