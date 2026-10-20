#!/bin/sh
set -eu
cd /home/ubuntu/prototype-v3-fused
.venv/bin/python software/latency/confirm_cse.py --threads 4 --spin-us 0 --main-core 3 --contexts 0.5 1 --runs 100 --nodes /encoder/encoder.1/mconv.1/conv/Conv_quant /encoder/encoder.1/mconv.6/conv/Conv_quant /encoder/encoder.1/mconv.11/conv/Conv_quant /encoder/encoder.1/mconv.16/conv/Conv_quant /encoder/encoder.3/res.0.0/conv/Conv_quant /encoder/encoder.4/mconv.16/conv/Conv_quant --out reports/fused/context_cse_short_confirmation100.json
