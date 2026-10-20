#!/bin/sh
# Run a supplied Python diagnostic under the existing, verified shortwide image.
set -eu
root=/home/ubuntu/prototype-v3-fused
cd "$root"
test "$(id -u)" = 0
kernel=$(uname -r)
test -s "deployment/kernel-compat/$kernel/shortwide/qn_tile.ko"
restore() {
    trap - EXIT
    rmmod qn_tile 2>/dev/null || true
    xmutil unloadapp || true
    xmutil loadapp asr-v3-bulk
    echo 100000000 > /sys/bus/platform/devices/asr-v3-bulk-clock/set_rate
    insmod "$root/deployment/kernel-compat/$kernel/bulk/qn_tile.ko"
    test -c /dev/qn-tile
}
trap restore EXIT
rmmod qn_tile 2>/dev/null || true
xmutil unloadapp
xmutil loadapp asr-v3-shortwide
echo 100000000 > /sys/bus/platform/devices/asr-v3-shortwide-clock/set_rate
insmod "$root/deployment/kernel-compat/$kernel/shortwide/qn_tile.ko"
test "$(cat /sys/module/qn_tile/parameters/short_cache_protocol)" = 1
test -c /dev/qn-tile
test "$(cat /sys/class/fpga_manager/fpga0/state)" = operating
.venv/bin/python "$@"
restore
