#!/bin/sh
set -eu
cd /home/ubuntu/prototype-v3-fused
.venv/bin/python software/latency/short_static_benchmark.py --nodes /encoder/encoder.1/mconv.1/conv/Conv_quant /encoder/encoder.1/mconv.6/conv/Conv_quant /encoder/encoder.1/mconv.11/conv/Conv_quant /encoder/encoder.1/mconv.16/conv/Conv_quant /encoder/encoder.3/res.0.0/conv/Conv_quant /encoder/encoder.4/mconv.16/conv/Conv_quant --contexts 0.5 1 --runs 50 --trim-padding --out reports/fused/short_trim_screen50.json
.venv/bin/python software/latency/short_static_benchmark.py --nodes /encoder/encoder.1/mconv.1/conv/Conv_quant /encoder/encoder.1/mconv.6/conv/Conv_quant /encoder/encoder.1/mconv.11/conv/Conv_quant /encoder/encoder.1/mconv.16/conv/Conv_quant /encoder/encoder.3/res.0.0/conv/Conv_quant /encoder/encoder.4/mconv.16/conv/Conv_quant --contexts 0.5 1 --runs 50 --freeze-length --out reports/fused/short_static_length_screen50.json
