#!/bin/sh
# Restore the board's existing K26 application, without changing QSPI.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run: sudo sh restore.sh' >&2; exit 1; }
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_active=$(xmutil listapps | awk -v mode=active -f "$task_root/package_listing.awk")
if [ -n "$task_active" ]; then
    xmutil unloadapp
fi
xmutil loadapp k26-starter-kits
xmutil listapps
