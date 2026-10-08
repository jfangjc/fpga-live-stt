#!/bin/sh
# Install package files only. Does not program the FPGA or change boot firmware.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run: sudo sh install.sh' >&2; exit 1; }
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$task_root"
sha256sum -c SHA256SUMS
task_dest=/lib/firmware/xilinx/voice-prototype
if [ -e "$task_dest" ]; then
    echo "$task_dest already exists. Preserve or inspect it before replacing it." >&2
    exit 1
fi
mkdir -p "$task_dest"
install -m 0644 voice-prototype/voice-prototype.bit.bin "$task_dest/"
install -m 0644 voice-prototype/voice-prototype.dtbo "$task_dest/"
install -m 0644 voice-prototype/shell.json "$task_dest/"
echo 'Installed voice-prototype. Check discovery with: sudo xmutil listapps'
echo 'Read README.md before running load_and_test.sh.'
