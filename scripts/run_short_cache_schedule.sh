#!/bin/sh
# Screen scheduling separately; restore the accepted application even on failure.
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
.venv/bin/python software/latency/tune_short_cache_schedule.py --cpu-runs 100 --runs 60 --out reports/fused/shortcache_schedule_screen.json
restore_bulk
echo 'Scheduling screen finished; accepted bulk firmware restored.'
