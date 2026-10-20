#!/bin/sh
set -eu
cd /home/ubuntu/prototype-v3-fused
.venv/bin/python software/latency/short_worker_trim_screen.py --spins 0 10 --runs 100 --out reports/fused/short_worker_trim_confirmation100.json
.venv/bin/python software/latency/validate_short_padding.py --nodes /encoder/encoder.1/mconv.6/conv/Conv_quant --out reports/fused/short_padding_single_validation.json
.venv/bin/python software/latency/validate_short_padding.py --nodes /encoder/encoder.1/mconv.1/conv/Conv_quant /encoder/encoder.1/mconv.6/conv/Conv_quant /encoder/encoder.1/mconv.11/conv/Conv_quant /encoder/encoder.1/mconv.16/conv/Conv_quant /encoder/encoder.3/res.0.0/conv/Conv_quant /encoder/encoder.4/mconv.16/conv/Conv_quant --out reports/fused/short_padding_six_validation.json
