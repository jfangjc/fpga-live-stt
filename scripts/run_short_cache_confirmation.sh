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
.venv/bin/python software/latency/confirm_short_cache_schedule.py --contexts .5 --runs 300 --out reports/fused/shortcache_scheduled_half.json
.venv/bin/python software/latency/confirm_short_cache_schedule.py --contexts 1 --runs 300 --out reports/fused/shortcache_scheduled_one.json
restore_bulk
echo 'Fresh scheduling confirmation finished; accepted bulk restored.'
