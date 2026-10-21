set -eu
cd /home/ubuntu/moonshine-kv260-20261020
export HF_HUB_CACHE=/home/ubuntu/.cache/huggingface/hub
export HF_HUB_OFFLINE=1
export PYTHONPATH="$PWD/software"
export PYTHONDONTWRITEBYTECODE=1
trap 'status=$?; echo "$status" > build/tiny-final.exit' EXIT
.venv/bin/python -m unittest discover -s tests -p test_moonshine.py -v > build/tiny-final-unit.log 2>&1
MOONSHINE_TEST_SIZE=tiny MOONSHINE_TEST_WAV=/home/ubuntu/kv260-asr-mvp-20261015/reports/test-inputs/speech_25.wav MOONSHINE_TEST_DECODER=build/tiny-decoder-v2 .venv/bin/python -m unittest discover -s tests -p test_moonshine_checkpoint.py -v > build/tiny-final-checkpoint.log 2>&1
set +e
.venv/bin/python scripts/run_moonshine_board.py --driver /home/ubuntu/kv260-asr-mvp-20261015/drivers/prebuilt/6.8.0-1036-xilinx/bulk/qn_tile.ko --evidence reports/local/tiny-ort-final-session.json -- .venv/bin/python scripts/benchmark_moonshine.py /home/ubuntu/kv260-asr-mvp-20261015/reports/test-inputs/speech_25.wav --out-dir reports/local/tiny-ort-final --size tiny --scope encoder-ffn --threads 2 --runs 3 --ort-decoder build/tiny-decoder-v2 --decoder-threads 4 --chunk-ms 1000
status=$?
set -e
if [ "$status" -ne 0 ] && [ "$status" -ne 2 ]; then exit "$status"; fi

.venv/bin/python scripts/run_moonshine_board.py --driver /home/ubuntu/kv260-asr-mvp-20261015/drivers/prebuilt/6.8.0-1036-xilinx/bulk/qn_tile.ko --evidence reports/local/tiny-ort-final-durations-session.json -- .venv/bin/python build/stress_tiny_final.py > build/tiny-final-durations.log 2>&1
