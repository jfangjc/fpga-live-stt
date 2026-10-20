#!/bin/sh
set -eu
cd /home/ubuntu/prototype-v3-fused
.venv/bin/python software/latency/short_cpu_threads_screen.py --contexts 0.5 1 --spin-us 0 --runs 30 --out reports/fused/short_cpu_threads_nonspin30.json
.venv/bin/python software/latency/short_cpu_threads_screen.py --contexts 0.5 1 --spin-us 10 --runs 30 --out reports/fused/short_cpu_threads_spin10_30.json
