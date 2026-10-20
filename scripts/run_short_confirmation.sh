#!/bin/sh
set -eu
cd /home/ubuntu/prototype-v3-fused
.venv/bin/python software/latency/context_short_policy.py --runtime bulk --threads 4 --spin-us 0 --main-core 3 --trim-padding --contexts 0.5 --runs 100 --nodes /encoder/encoder.1/mconv.6/conv/Conv_quant --out reports/fused/short_half_second_confirmation100.json
.venv/bin/python software/latency/bind_short_profile.py --benchmark reports/fused/short_half_second_confirmation100.json --validation reports/fused/short_padding_single_validation.json --out reports/fused/short_half_second_deployment.json
.venv/bin/python software/latency/context_short_policy.py --runtime bulk --threads 4 --spin-us 10 --main-core 3 --trim-padding --contexts 1 --runs 100 --nodes /encoder/encoder.1/mconv.1/conv/Conv_quant /encoder/encoder.1/mconv.6/conv/Conv_quant /encoder/encoder.1/mconv.11/conv/Conv_quant /encoder/encoder.1/mconv.16/conv/Conv_quant /encoder/encoder.3/res.0.0/conv/Conv_quant /encoder/encoder.4/mconv.16/conv/Conv_quant --out reports/fused/short_one_second_confirmation100.json
.venv/bin/python software/latency/bind_short_profile.py --benchmark reports/fused/short_one_second_confirmation100.json --validation reports/fused/short_padding_six_validation.json --out reports/fused/short_one_second_deployment.json
