set -eu
cd /home/ubuntu/moonshine-kv260-20261020
export HF_HUB_CACHE=/home/ubuntu/.cache/huggingface/hub
export HF_HUB_OFFLINE=1
export PYTHONPATH="$PWD/software"
export PYTHONDONTWRITEBYTECODE=1
export OMP_WAIT_POLICY=PASSIVE
trap 'status=$?; echo "$status" > build/small-qualify.exit' EXIT
combined=0
set +e
.venv/bin/python scripts/run_moonshine_board.py --driver /home/ubuntu/kv260-asr-mvp-20261015/drivers/prebuilt/6.8.0-1036-xilinx/bulk/qn_tile.ko --evidence reports/local/small-ort-final-durations-session.json -- .venv/bin/python scripts/benchmark_moonshine_durations.py /home/ubuntu/kv260-asr-mvp-20261015/reports/test-inputs/speech_25.wav --size small --ort-decoder build/small-decoder-v1 --chunk-ms 2500 --threads 2 --decoder-threads 4 --repeat 1 2 --runs 3 --out reports/local/small-ort-final-durations.json
status=$?
set -e
if [ "$status" -eq 2 ]; then combined=2; elif [ "$status" -ne 0 ]; then exit "$status"; fi
set +e
.venv/bin/python scripts/run_moonshine_board.py --driver /home/ubuntu/kv260-asr-mvp-20261015/drivers/prebuilt/6.8.0-1036-xilinx/bulk/qn_tile.ko --evidence reports/local/tiny-packets-regression-session.json -- .venv/bin/python scripts/benchmark_moonshine_durations.py /home/ubuntu/kv260-asr-mvp-20261015/reports/test-inputs/speech_25.wav --size tiny --ort-decoder build/tiny-decoder-v2 --chunk-ms 1000 --threads 2 --decoder-threads 4 --repeat 1 --runs 3 --out reports/local/tiny-packets-regression.json
status=$?
set -e
if [ "$status" -eq 2 ]; then combined=2; elif [ "$status" -ne 0 ]; then exit "$status"; fi
exit "$combined"
