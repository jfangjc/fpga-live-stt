#!/bin/sh
# Start the long qualification with output retained if the SSH session closes.
set -eu
test "$(id -u)" = 0
project=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work=$(realpath "${1:?Work directory required}")
release=$(realpath "${2:?Release containing the compatible driver required}")
cd "$work"
test ! -e pipeline_state.json
test ! -e qualification_pipeline.log
set -C
nohup python3 "$project/software/whisper/qualify_board.py" --work "$work" --release "$release" \
    > qualification_pipeline.log 2>&1 < /dev/null &
echo "$!" > qualification_launcher.pid
cat qualification_launcher.pid
