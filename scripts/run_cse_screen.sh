#!/bin/sh
set -eu
cd /home/ubuntu/prototype-v3-fused
.venv/bin/python software/latency/cpu_cse_thread_screen.py --runs 30 --out reports/fused/context_cse_cpu_thread_screen30.json
.venv/bin/python software/latency/context_cse_policy.py --runtime bulk --threads 4 --spin-us 1000 --runs 50 --nodes /encoder/encoder.1/mconv.1/conv/Conv_quant /encoder/encoder.1/mconv.6/conv/Conv_quant /encoder/encoder.1/mconv.11/conv/Conv_quant /encoder/encoder.1/mconv.16/conv/Conv_quant /encoder/encoder.3/res.0.0/conv/Conv_quant /encoder/encoder.4/mconv.16/conv/Conv_quant --out reports/fused/context_cse_spin1000_screen50.json
.venv/bin/python software/latency/validate_cse_physical.py --nodes /encoder/encoder.1/mconv.1/conv/Conv_quant /encoder/encoder.1/mconv.6/conv/Conv_quant /encoder/encoder.1/mconv.11/conv/Conv_quant /encoder/encoder.1/mconv.16/conv/Conv_quant /encoder/encoder.3/res.0.0/conv/Conv_quant /encoder/encoder.4/mconv.16/conv/Conv_quant --out reports/fused/cse_physical_validation.json
