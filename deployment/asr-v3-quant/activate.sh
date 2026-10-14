#!/bin/sh
# Run as root only after host timing/simulation gates and firmware installation.
set -eu
module=/home/ubuntu/prototype-v3-fused/deployment/experimental-quant/qn_tile.ko
rollback_module=/home/ubuntu/prototype-v2-package/deployment/driver/6.8.0-1015-xilinx/qn_tile_cached.ko
firmware=/lib/firmware/xilinx/asr-v3-quant
test "$(id -u)" = 0
test -f "$module"
test -f "$rollback_module"
test -s "$firmware/asr-v3-quant.bit.bin"
test -s "$firmware/asr-v3-quant.dtbo"
test -s "$firmware/shell.json"
rollback() {
    trap - EXIT
    echo 'Experimental activation failed; restoring asr-v2.' >&2
    rmmod qn_tile 2>/dev/null || true
    xmutil unloadapp || true
    xmutil loadapp asr-v2
    echo 100000000 > /sys/bus/platform/devices/asr-v2-clock/set_rate
    insmod "$rollback_module"
    exit 1
}
# rmmod fails if a client is still using the device, before unloading the app.
rmmod qn_tile
trap rollback EXIT
xmutil unloadapp
xmutil loadapp asr-v3-quant
echo 100000000 > /sys/bus/platform/devices/asr-v3-quant-clock/set_rate
insmod "$module"
test "$(cat /sys/module/qn_tile/parameters/quant_protocol)" = 1
test "$(cat /sys/module/qn_tile/parameters/rx_capacity)" = 4194304
test -c /dev/qn-tile
test "$(cat /sys/class/fpga_manager/fpga0/state)" = operating
xmutil listapps
cat /sys/bus/platform/devices/asr-v3-quant-clock/set_rate
trap - EXIT
echo 'Matching quantized FPGA application and driver active.'
