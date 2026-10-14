#!/bin/sh
set -eu
cd /home/ubuntu/prototype-v3-fused
for threads in 1 2 4; do
    .venv/bin/python software/ort_fpga_pair/benchmark_block.py --cpu-only --threads "$threads" --seconds 0.5 --runs 200 --out "reports/fused/pair_cpu_block_half_threads${threads}.json"
    .venv/bin/python software/ort_fpga_pair/benchmark_block.py --cpu-only --threads "$threads" --seconds 1 --runs 200 --out "reports/fused/pair_cpu_block_one_threads${threads}.json"
done
