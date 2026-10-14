#!/bin/sh
set -eu
# Reuse existing downloaded Linux toolchain/sysroot read-only. Only output new tree.
native_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
tool_root=${QNC_TOOL_ROOT:-/mnt/c/Users/jfang/Documents/Vivado/Prototype/software/tile-driver/kernel-build/sysroot}
target_root=${QNC_TARGET_ROOT:-/mnt/c/Users/jfang/Documents/Vivado/Prototype/software/asr-baseline/native/build/sysroot}
export LD_LIBRARY_PATH="$tool_root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="$tool_root/usr/bin:$PATH"
mkdir -p "$native_dir/prebuilt/aarch64"
compile() {
"$tool_root/usr/bin/aarch64-linux-gnu-gcc-13" -O3 -std=c11 -Wall -Wextra -Werror \
 -fno-fast-math -ffp-contract=off -mcpu=cortex-a53 \
 --sysroot="$target_root" \
 -B"$target_root/usr/lib/gcc-cross/aarch64-linux-gnu/13/" \
 -B"$target_root/usr/aarch64-linux-gnu/lib/" \
 -isystem "$target_root/usr/lib/gcc-cross/aarch64-linux-gnu/13/include" \
 -isystem "$target_root/usr/aarch64-linux-gnu/include" \
 -L"$target_root/usr/lib/gcc-cross/aarch64-linux-gnu/13" \
 -L"$target_root/usr/aarch64-linux-gnu/lib" \
 "$@"
}
compile -fPIC -shared "$native_dir/qnc.c" -lm -o "$native_dir/prebuilt/aarch64/libqnc.so"
if [ "${QNC_BUILD_TESTS:-0}" = 1 ]; then
 compile "$native_dir/qnc.c" "$native_dir/test_qnc.c" -lm -o "$native_dir/prebuilt/aarch64/test_qnc_neon"
 compile -DQNC_FORCE_SCALAR "$native_dir/qnc.c" "$native_dir/test_qnc.c" -lm -o "$native_dir/prebuilt/aarch64/test_qnc_scalar"
fi
