#!/bin/sh
# Run as root after pair firmware installation. Always restore accepted bulk.
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
sh deployment/asr-v3-cache/activate.sh
trap restore_bulk EXIT
.venv/bin/python software/ort_fpga_cache/smoke.py --physical --out reports/fused/cache_physical_synthetic.json
.venv/bin/python software/ort_fpga_cache/validate.py --physical --out reports/fused/cache_physical_validation.json
.venv/bin/python software/ort_fpga_cache/run_latency_checks.py
.venv/bin/python software/ort_fpga_cache/check_resident.py
restore_bulk
echo 'Cache physical checks finished; accepted bulk deployment restored.'
