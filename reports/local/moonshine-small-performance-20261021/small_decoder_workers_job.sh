set -eu
cd /home/ubuntu/moonshine-kv260-20261020
export HF_HUB_CACHE=/home/ubuntu/.cache/huggingface/hub
export HF_HUB_OFFLINE=1
export PYTHONPATH="$PWD/software"
export PYTHONDONTWRITEBYTECODE=1
export OMP_WAIT_POLICY=PASSIVE
trap 'status=$?; echo "$status" > build/small-workers.exit' EXIT
sh scripts/build_moonshine.sh > build/small-packets-build.log 2>&1
.venv/bin/python scripts/run_moonshine_board.py --driver /home/ubuntu/kv260-asr-mvp-20261015/drivers/prebuilt/6.8.0-1036-xilinx/bulk/qn_tile.ko --evidence reports/local/small-packets-physical-v2-session.json -- .venv/bin/python scripts/test_moonshine_physical.py --out reports/local/small-packets-physical-v2.json > build/small-packets-physical-v2.log 2>&1
.venv/bin/python scripts/run_moonshine_board.py --driver /home/ubuntu/kv260-asr-mvp-20261015/drivers/prebuilt/6.8.0-1036-xilinx/bulk/qn_tile.ko --evidence reports/local/small-workers-session.json -- .venv/bin/python build/probe_small_decoder.py
