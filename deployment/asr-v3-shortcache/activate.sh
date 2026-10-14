#!/bin/sh
# Activate only a gated pair image; restore the accepted bulk image on failure.
set -eu
root=/home/ubuntu/prototype-v3-fused
test "$(id -u)" = 0
test -s "$root/reports/fused/shortcache_firmware_evidence.json"
test -s /lib/firmware/xilinx/asr-v3-shortcache/asr-v3-shortcache.bit.bin
test -s "$root/deployment/experimental-shortcache/qn_tile.ko"
rollback() {
    trap - EXIT
    rmmod qn_tile 2>/dev/null || true
    xmutil unloadapp || true
    xmutil loadapp asr-v3-bulk
    echo 100000000 > /sys/bus/platform/devices/asr-v3-bulk-clock/set_rate
    insmod "$root/deployment/experimental-bulk/qn_tile.ko"
    exit 1
}
rmmod qn_tile
trap rollback EXIT
xmutil unloadapp
xmutil loadapp asr-v3-shortcache
echo 100000000 > /sys/bus/platform/devices/asr-v3-shortcache-clock/set_rate
insmod "$root/deployment/experimental-shortcache/qn_tile.ko"
test "$(cat /sys/module/qn_tile/parameters/short_cache_protocol)" = 1
test -c /dev/qn-tile
test "$(cat /sys/class/fpga_manager/fpga0/state)" = operating
trap - EXIT
echo 'Experimental retained depthwise/pointwise image active.'
