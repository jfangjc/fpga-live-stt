#!/bin/sh
set -eu
cd /home/ubuntu/prototype-v3-fused
.venv/bin/python software/latency/context_cse_affinity.py --runtime bulk --threads 4 --spin-us 0 --main-core 3 --contexts 0.5 1 --runs 30 --nodes /encoder/encoder.1/mconv.1/conv/Conv_quant --out reports/fused/short_resident_node0_screen30.json
.venv/bin/python software/latency/context_cse_affinity.py --runtime bulk --threads 4 --spin-us 0 --main-core 3 --contexts 0.5 1 --runs 30 --nodes /encoder/encoder.1/mconv.6/conv/Conv_quant --out reports/fused/short_resident_node1_screen30.json
.venv/bin/python software/latency/context_cse_affinity.py --runtime bulk --threads 4 --spin-us 0 --main-core 3 --contexts 0.5 1 --runs 30 --nodes /encoder/encoder.1/mconv.11/conv/Conv_quant --out reports/fused/short_resident_node2_screen30.json
.venv/bin/python software/latency/context_cse_affinity.py --runtime bulk --threads 4 --spin-us 0 --main-core 3 --contexts 0.5 1 --runs 30 --nodes /encoder/encoder.1/mconv.16/conv/Conv_quant --out reports/fused/short_resident_node3_screen30.json
.venv/bin/python software/latency/context_cse_affinity.py --runtime bulk --threads 4 --spin-us 0 --main-core 3 --contexts 0.5 1 --runs 30 --nodes /encoder/encoder.3/res.0.0/conv/Conv_quant --out reports/fused/short_resident_node4_screen30.json
.venv/bin/python software/latency/context_cse_affinity.py --runtime bulk --threads 4 --spin-us 0 --main-core 3 --contexts 0.5 1 --runs 30 --nodes /encoder/encoder.4/mconv.16/conv/Conv_quant --out reports/fused/short_resident_node5_screen30.json
