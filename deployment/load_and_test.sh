#!/bin/sh
# Replaces the active PL application, then performs a short operator/audio test.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run: sudo sh load_and_test.sh' >&2; exit 1; }
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$task_root"
sha256sum -c SHA256SUMS
command -v xmutil >/dev/null
command -v python3 >/dev/null
[ -d /sys/class/fpga_manager/fpga0 ] || { echo 'FPGA Manager missing'; exit 1; }
for task_name in voice-prototype.bit.bin voice-prototype.dtbo shell.json; do
    cmp -s "voice-prototype/$task_name" "/lib/firmware/xilinx/voice-prototype/$task_name" || {
        echo "Installed $task_name is missing or differs from this package." >&2
        exit 1
    }
done
task_listing=$(xmutil listapps)
printf '%s\n' "$task_listing"
printf '%s\n' "$task_listing" | awk -v mode=present -v name=voice-prototype -v type=PL_FLAT -f package_listing.awk || {
    echo 'voice-prototype is not discovered as PL_FLAT; current application was not unloaded.' >&2
    exit 1
}
if [ ! -d /sys/bus/platform/drivers/uio_pdrv_genirq ]; then
    modprobe uio_pdrv_genirq of_id=generic-uio
fi
[ -d /sys/bus/platform/drivers/uio_pdrv_genirq ] || {
    echo 'uio_pdrv_genirq driver unavailable; current application was not unloaded.' >&2
    exit 1
}
# of_id has sysfs permissions 0 in this driver. Validate the actual UIO binding
# and mapping below rather than reading a nonexistent module parameter file.
# These drivers may be built in, so missing module files alone are not decisive.
[ -d /sys/bus/platform/drivers/xilinx_fclk ] || modprobe xilinx_fclk || true
[ -d /sys/bus/platform/drivers/afi-fpga ] || modprobe xilinx-afi || true
[ -d /sys/bus/platform/drivers/xilinx_fclk ] || { echo 'xilinx_fclk driver unavailable'; exit 1; }
[ -d /sys/bus/platform/drivers/afi-fpga ] || { echo 'afi-fpga driver unavailable'; exit 1; }
echo 'Replacing the currently active PL application with voice-prototype.'
task_active=$(printf '%s\n' "$task_listing" | awk -v mode=active -f package_listing.awk)
if [ -n "$task_active" ]; then
    echo "Unloading $task_active"
    xmutil unloadapp
else
    echo 'No active flat PL application; skipping unload.'
fi
xmutil loadapp voice-prototype
task_clock_bound=0
task_afi_bound=0
task_uio_device=
task_clock_rate=
task_tries=0
while [ "$task_tries" -lt 20 ]; do
    for task_dev in /sys/bus/platform/devices/*voice*; do
        [ -L "$task_dev/driver" ] || continue
        task_driver=$(basename "$(readlink -f "$task_dev/driver")")
        case "$task_driver" in
            xilinx_fclk)
                task_clock_bound=1
                task_clock_rate=$(cat "$task_dev/set_rate")
                ;;
            afi-fpga) task_afi_bound=1 ;;
        esac
    done
    for task_uio in /sys/class/uio/uio*; do
        [ -f "$task_uio/name" ] || continue
        [ "$(cat "$task_uio/name")" = voice-prototype ] || continue
        task_addr=$(cat "$task_uio/maps/map0/addr")
        task_size=$(cat "$task_uio/maps/map0/size")
        [ "$((task_addr))" -eq 2684354560 ] || { echo 'Unexpected UIO address'; exit 1; }
        [ "$((task_size))" -eq 65536 ] || { echo 'Unexpected UIO size'; exit 1; }
        task_uio_device=/dev/$(basename "$task_uio")
    done
    if [ "$task_clock_bound" = 1 ] && [ "$task_afi_bound" = 1 ] && [ -n "$task_uio_device" ]; then
        break
    fi
    task_tries=$((task_tries + 1))
    sleep 1
done
if [ "$task_clock_bound" != 1 ] || [ "$task_afi_bound" != 1 ] || [ -z "$task_uio_device" ]; then
    echo 'Clock, AFI or UIO binding failed; no MMIO access was attempted.' >&2
    echo 'Collect: sudo dmesg | tail -100; sudo xmutil listapps' >&2
    exit 1
fi
[ "$(cat /sys/class/fpga_manager/fpga0/state)" = operating ] || {
    echo 'FPGA Manager does not report operating; no MMIO access attempted.' >&2
    exit 1
}
[ "$task_clock_rate" -ge 99998000 ] && [ "$task_clock_rate" -le 100000000 ] || {
    echo "Unexpected PL0 rate $task_clock_rate Hz; no MMIO access attempted." >&2
    exit 1
}
echo "PL0 clock rate: $task_clock_rate Hz"
echo "Testing $task_uio_device; expected signed dot result: -32384"
python3 board_smoke.py "$task_uio_device"
echo 'Smoke test finished. This does not execute the complete QuartzNet network.'
