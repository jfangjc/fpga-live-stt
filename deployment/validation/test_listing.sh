#!/bin/sh
set -eu
task_parser=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/package_listing.awk
task_new='3 PL_FLAT - - voice-pr... id_ok PL_FLAT (0+0+0) -1 voice-prototype'
task_old='voice-prototype PL_FLAT voice-prototype id_ok PL_FLAT (0+0+0) -1'
printf '%s\n' "$task_new" | awk -v mode=present -v name=voice-prototype -v type=PL_FLAT -f "$task_parser"
printf '%s\n' "$task_old" | awk -v mode=present -v name=voice-prototype -v type=PL_FLAT -f "$task_parser"
if printf '%s\n' '3 PL_FLAT - - voice-pr... id_ok PL_FLAT (0+0+0) -1 voice-prototype-other' | awk -v mode=present -v name=voice-prototype -v type=PL_FLAT -f "$task_parser"; then
    echo 'FAIL: similarly named package accepted'; exit 1
fi
if printf '%s\n' '3 XRT_FLAT - - voice-pr... id_ok XRT_FLAT (0+0+0) -1 voice-prototype' | awk -v mode=present -v name=voice-prototype -v type=PL_FLAT -f "$task_parser"; then
    echo 'FAIL: incorrect package type accepted'; exit 1
fi
[ -z "$(printf '%s\n' "$task_new" | awk -v mode=active -f "$task_parser")" ]
[ "$(printf '%s\n' '2 XRT_FLAT - - k26-star... id_ok XRT_FLAT (0+0+0) 0->0, k26-starter-kits' | awk -v mode=active -f "$task_parser")" = k26-starter-kits ]
[ "$(printf '%s\n' 'k26-starter-kits XRT_FLAT k26-starter-kits id_ok XRT_FLAT (0+0+0) 0->0,' | awk -v mode=active -f "$task_parser")" = k26-starter-kits ]
echo 'PASS: legacy/new discovery, exact name/type rejection, active and inactive detection'
