#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

prefix=/opt/stt-caption
[ "$(id -u)" = 0 ] || { echo "install.sh: run as root" >&2; exit 1; }

# The board programs, with cmake when the board has it and the same sources straight through cc otherwise
if command -v cmake >/dev/null; then
    cmake -S app -B build/app -G "Unix Makefiles"
    cmake --build build/app
else
    mkdir -p build/app
    flags="-O2 -mcpu=cortex-a53 -std=c11 -Wall -Wextra"
    common="app/kv260.c app/hybrid.c app/cpu.c app/phrase.c app/live.c"
    cc $flags -o build/app/caption app/caption.c $common -lm -pthread
    cc $flags -o build/app/transcript app/transcript.c $common -lm -pthread
    cc $flags -o build/app/screen app/screen.c app/display.c app/term.c app/settle.c $common -lm -pthread
fi
(cd u-dma-buf && make)

for dm in gdm3 gdm lightdm sddm; do
    systemctl disable --now "$dm" 2>/dev/null || true
done
if [ -w /sys/class/graphics/fb0/blank ]; then
    echo 0 > /sys/class/graphics/fb0/blank || true
fi

systemctl stop stt-caption 2>/dev/null || true
install -d "$prefix/bin" "$prefix/share" "$prefix/lib" \
           /lib/firmware/xilinx/stt-kv260 /var/lib/stt-caption/sessions

install -m 755 build/app/caption build/app/screen build/app/transcript stt-caption "$prefix/bin/"
install -m 755 uninstall.sh "$prefix/"
install -m 644 quartznet_engine.bin running_prior.json "$prefix/share/"
# The cpu runner's weights, if packaged
[ -e quartznet_int8.bin ] && install -m 644 quartznet_int8.bin "$prefix/share/"
install -m 644 u-dma-buf/u-dma-buf.ko "$prefix/lib/"
install -m 644 stt-kv260/* /lib/firmware/xilinx/stt-kv260/

[ -e /etc/default/stt-caption ] || install -m 644 stt-caption.conf /etc/default/stt-caption
install -m 644 stt-caption.service /etc/systemd/system/
systemctl daemon-reload

if [ "${1:-}" = "--enable" ]; then
    systemctl enable --now stt-caption
fi
