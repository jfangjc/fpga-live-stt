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
.venv/bin/python software/ort_fpga_shortwide/smoke.py --physical --out reports/fused/shortwide_physical_synthetic.json
.venv/bin/python software/ort_fpga_shortwide/validate.py --physical --out reports/fused/shortwide_physical_validation.json
.venv/bin/python software/latency/confirm_short_wide_schedule.py --contexts .5 --runs 300 --out reports/fused/shortwide_scheduled_half.json
.venv/bin/python software/latency/confirm_short_wide_schedule.py --contexts 1 --runs 300 --out reports/fused/shortwide_scheduled_one.json
.venv/bin/python software/latency/check_short_wide_resident.py
restore_bulk
.venv/bin/python scripts/verify_short_wide_restoration.py
echo 'Wider depthwise physical validation finished; accepted bulk restored.'
