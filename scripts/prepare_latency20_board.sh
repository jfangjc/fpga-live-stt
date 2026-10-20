#!/bin/sh
# Preserve original modules; build compatible copies for the running kernel.
set -eu
root=/home/ubuntu/prototype-v3-fused
cd "$root"
kernel=$(uname -r)
for design in bulk shortwide; do
    target="deployment/kernel-compat/$kernel/$design"
    mkdir -p "$target"
    cp "deployment/experimental-$design/"*.c "$target/"
    cp "deployment/experimental-$design/"*.h "$target/"
    cp "deployment/experimental-$design/Makefile" "$target/"
    make -C "$target" -j4
    modinfo -F vermagic "$target/qn_tile.ko"
done
printf 'Compatible driver copies built for %s; no original artifact replaced.\n' "$kernel"
