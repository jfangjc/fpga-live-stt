#!/bin/bash
set -eu
root=/mnt/c/Users/jfang/Documents/Vivado/Prototype/software/tile-driver/kernel-build
headers=$root/sysroot/usr/src/linux-headers-6.8.0-1015-xilinx
common=$root/sysroot/usr/src/linux-xilinx-headers-6.8.0-1015
export LD_LIBRARY_PATH=$root/sysroot/usr/lib/x86_64-linux-gnu
export PATH=$root/sysroot/usr/bin:$PATH
cc=$root/sysroot/usr/bin/aarch64-linux-gnu-gcc-13
gcc -O2 -o "$headers/scripts/basic/fixdep" "$common/scripts/basic/fixdep.c"
gcc -O2 -I"$headers/scripts/mod" -I"$common/scripts/mod" -o "$headers/scripts/mod/modpost" "$common/scripts/mod/modpost.c" "$common/scripts/mod/file2alias.c" "$common/scripts/mod/sumversion.c" "$common/scripts/mod/symsearch.c"
make -C "$headers" M="$root/.." ARCH=arm64 CROSS_COMPILE=$root/sysroot/usr/bin/aarch64-linux-gnu- CC="$cc" LD=$root/sysroot/usr/bin/aarch64-linux-gnu-ld.bfd W=1 modules
