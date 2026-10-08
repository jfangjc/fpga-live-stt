#!/bin/bash
set -eu
workspace=/mnt/c/Users/jfang/Documents/Vivado/Prototype
native=$workspace/software/asr-baseline/native
hosttools=$workspace/software/tile-driver/kernel-build/sysroot
sysroot=$native/build/sysroot
export LD_LIBRARY_PATH=$hosttools/usr/lib/x86_64-linux-gnu
export PATH=$hosttools/usr/bin:$PATH
cc=$hosttools/usr/bin/aarch64-linux-gnu-gcc-13
set -x
"$cc" -O3 -std=c11 -Wall -Wextra -Werror -fno-fast-math -ffp-contract=off \
 -mcpu=cortex-a53 -fPIC -shared -pthread --sysroot="$sysroot" \
 -B"$sysroot/usr/lib/gcc-cross/aarch64-linux-gnu/13/" \
 -B"$sysroot/usr/aarch64-linux-gnu/lib/" \
 -isystem "$sysroot/usr/lib/gcc-cross/aarch64-linux-gnu/13/include" \
 -isystem "$sysroot/usr/aarch64-linux-gnu/include" \
 -L"$sysroot/usr/lib/gcc-cross/aarch64-linux-gnu/13" \
 -L"$sysroot/usr/aarch64-linux-gnu/lib" \
 -o "$native/prebuilt/libqn_depthwise_aarch64.so" "$native/qn_depthwise.c"
