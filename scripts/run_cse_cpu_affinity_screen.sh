#!/bin/sh
set -eu
cd /home/ubuntu/prototype-v3-fused
.venv/bin/python software/latency/cpu_cse_affinity_screen.py --main-core 3 --contexts 0.5 1 --threads 1 2 4 --spin-us 0 --runs 30 --out reports/fused/context_cse_affinity_cpu_nonspin30.json
.venv/bin/python software/latency/cpu_cse_affinity_screen.py --main-core 3 --contexts 0.5 1 --threads 2 4 --spin-us 1000 --runs 30 --out reports/fused/context_cse_affinity_cpu_spin1000_30.json
