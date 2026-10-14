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
sh deployment/asr-v3-shortcache/activate.sh
trap restore_bulk EXIT
.venv/bin/python software/latency/check_short_cache_scheduled_resident.py
restore_bulk
.venv/bin/python scripts/verify_short_cache_scheduled_restoration.py
echo 'Scheduled resident API verified; accepted bulk restored.'
