#!/bin/sh
set -eu
cd /home/ubuntu/prototype-v3-fused
.venv/bin/python software/latency/resident.py --benchmark reports/fused/context_spin1000_confirmation100.json --backend fpga --wav research/eval/user-recording/speech.wav --repeats 3 > reports/fused/latency_resident_fpga.jsonl
.venv/bin/python software/latency/resident.py --benchmark reports/fused/context_spin1000_confirmation100.json --backend cpu --wav research/eval/user-recording/speech.wav --repeats 3 > reports/fused/latency_resident_cpu.jsonl
sha256sum software/latency/resident.py
