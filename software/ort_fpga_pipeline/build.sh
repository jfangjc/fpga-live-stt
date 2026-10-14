#!/bin/sh
set -eu
cd "$(dirname "$0")"
gcc -O3 -fPIC -std=c11 -c qnc_transport.c -o qnc.o
g++ -O3 -fPIC -std=c++17 -shared pointwise.cc qnc.o -o libort_fpga.so -pthread -lm
