#!/bin/sh
# Read-only hardware/software inventory; only writes two local report files.
# Run on the KV260: sh collect_board_profile.sh
set -eu
task_output_dir=${1:-"$PWD"}
mkdir -p "$task_output_dir"
sudo dtc -I fs -O dts -o "$task_output_dir/voice-board.dts" /sys/firmware/devicetree/base
{
    cat /etc/os-release
    uname -a
    sudo xmutil bootfw_status
    sudo xmutil listapps
    dpkg-query -W -f='${Package} ${Version}\n' '*dfx*' '*xmutil*' '*libdfx*' 2>/dev/null || true
    for task_symbol in fpga_full amba zynqmp_clk gic; do
        task_symbol_path="/sys/firmware/devicetree/base/__symbols__/$task_symbol"
        if [ -f "$task_symbol_path" ]; then
            printf '%s: ' "$task_symbol"
            tr -d '\000' < "$task_symbol_path"
            printf '\n'
        fi
    done
    for task_uio in /sys/class/uio/uio*; do
        [ -d "$task_uio" ] || continue
        printf '\n%s\n' "$task_uio"
        cat "$task_uio/name"
        cat "$task_uio/maps/map0/addr" "$task_uio/maps/map0/size"
    done
} > "$task_output_dir/voice-board-info.txt"
printf 'Created %s/voice-board.dts and %s/voice-board-info.txt\n' "$task_output_dir" "$task_output_dir"
