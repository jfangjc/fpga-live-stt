# Reproducing the KV260 run

Use `BENCHMARK_REPORT.md` for the measured results and qualifications. The original benchmark supplied by the user remains at its original path; this directory is the adapted copy.

`kv260-results.zip` contains measurements, transcripts, logs, the clip manifest, scripts and metadata. The audio and model weights remain in the working directory and on the board; they are not duplicated in the ZIP. The commands below recreate the audio and weights.

The tested board was `ubuntu@192.168.1.111`. All inference uses its Cortex-A53 CPU.

## Board environment

```sh
sudo apt-get install -y python3-venv libportaudio2 libsndfile1
python3 -m venv .venv
.venv/bin/pip install numpy==2.5.4 soundfile==0.14.0 jiwer==4.0.0 \
    onnxruntime==1.31.1 faster-whisper==1.2.1 ctranslate2==4.8.4 \
    moonshine-voice==0.1.5
# This benchmark only uses the array-based inference path. Its optional audio
# loading dependencies (librosa/numba) are not needed for that path.
.venv/bin/pip install --no-deps useful-moonshine-onnx==20251121
```

The exact 40 WAV files and `manifest.tsv` are saved in `data/`. To regenerate them from the official LibriSpeech test-clean archive:

```sh
curl -L --fail -o test-clean.tar.gz https://www.openslr.org/resources/12/test-clean.tar.gz
tar xzf test-clean.tar.gz
.venv/bin/python prepare_data.py LibriSpeech/test-clean --n 40 --seed 0
```

## NVIDIA exports on an x86 PC

The four ONNX exports and their configurations are already saved in `nemo/`. To recreate them, use Linux or WSL with Python 3.11 and the versions in `requirements-export-freeze.txt`. Install the CPU PyTorch wheels from `https://download.pytorch.org/whl/cpu`. Keep the export directory in WSL's native filesystem for efficient checkpoint extraction.

Run `export_nemo.py` with the `data/` directory present. It skips checkpoints that already have a validation record. For a deliberate re-export, move that checkpoint's `.onnx` and `.validation.json` aside first. It initializes a long mask cache, traces a short input with dynamic axes, compares NumPy features with NeMo's preprocessor, and tests the shortest and longest speech clips.

Copy the four `.onnx` files and their matching `.json` configurations to `nemo/` on the board. The `.nemo` training checkpoints are not required on the board.

## Run all models sequentially

Finish all setup and transfers before timing:

```sh
.venv/bin/python prefetch.py
.venv/bin/python environment.py
sync
.venv/bin/python -u run_suite.py --initial-cooldown 30 --out results-new
```

`run_suite.py` runs each model in its own process, in the requested order. Each child loads all 40 clips into memory, loads its model, runs two untimed warmup clips, then measures all 40 clips. The suite waits 30 seconds between models. It writes progress to RAM and copies each model's finished output to the selected results directory before moving on. Keep the session alive until it completes; its finished per-model outputs are durable on disk.

Use a fresh `--out` directory for an independent run. To run a subset, use `--models` with keys listed in `models.py`. The lower-level `bench.py` entry point and timing/aggregation method remain available.

`results/status.json` retains the failed initial Citrinet-1024 warmup attempt and its successful retry. The failed attempt's log is preserved in `results/attempts/`; no latency from that attempt enters the results.
