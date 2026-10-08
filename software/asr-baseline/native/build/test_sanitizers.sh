#!/bin/bash
set -eu
native=/mnt/c/Users/jfang/Documents/Vivado/Prototype/software/asr-baseline/native
libs=$native/build/sysroot/usr/lib/x86_64-linux-gnu
cd "$native"
gcc -O1 -g -std=c11 -Wall -Wextra -Werror -fno-fast-math -ffp-contract=off -fsanitize=address,undefined -fno-omit-frame-pointer -pthread -c qn_depthwise.c -o host/qn_depthwise_sanitizer.o
gcc -O1 -g -std=c11 -Wall -Wextra -Werror -fno-fast-math -ffp-contract=off -fsanitize=address,undefined -fno-omit-frame-pointer -pthread -c test_sanitizer.c -o host/test_sanitizer.o
gcc -pthread host/qn_depthwise_sanitizer.o host/test_sanitizer.o -L"$libs" -Wl,-rpath,"$libs" -l:libasan.so.8 -l:libubsan.so.1 -o host/test_sanitizer
host/test_sanitizer
