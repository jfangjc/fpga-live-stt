#!/bin/sh
set -eu
cd /home/ubuntu/prototype-v3-fused
.venv/bin/python software/latency/bind_short_profile.py --benchmark reports/fused/short_half_second_confirmation100.json --validation reports/fused/short_padding_single_validation.json --out reports/fused/short_half_second_deployment.json
.venv/bin/python software/latency/bind_short_profile.py --benchmark reports/fused/short_irq3_one_confirmation300.json --validation reports/fused/short_padding_six_validation.json --out reports/fused/short_one_second_irq3_deployment.json
.venv/bin/python software/latency/smoke_short_resident.py
.venv/bin/python software/latency/smoke_cse_resident.py
