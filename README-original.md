# KV260 STT preliminary benchmark

Offline latency, RTF, WER and peak memory for 7 models on the KV260's A53 CPU.

| Key | Model | Runtime |
|---|---|---|
| whisper-tiny.en / base.en / small.en | OpenAI Whisper | faster-whisper (CTranslate2 int8) |
| moonshine-tiny / moonshine-base | Moonshine | ONNX Runtime |
| quartznet15x5 / citrinet256 | NVIDIA NeMo CTC | ONNX Runtime + numpy features |

Edit `MODELS` in `models.py` to change the list.

## Steps

1. **On an x86 PC:** `pip install "nemo_toolkit[asr]" && python export_nemo.py`, then copy `nemo/` to the board.
2. **On the KV260:**
   ```sh
   pip install -r requirements.txt
   wget https://www.openslr.org/resources/12/test-clean.tar.gz && tar xzf test-clean.tar.gz
   python3 prepare_data.py LibriSpeech/test-clean --n 40
   sudo sh -c 'echo performance > /sys/devices/system/cpu/cpufreq/policy0/scaling_governor'
   python3 bench.py --models moonshine-tiny --warmup 1   # first run downloads weights; ignore its load_s
   python3 bench.py
   ```

## Output

`results/summary.csv` holds one row per model. `results/<model>.csv` holds per-clip timings plus reference and hypothesis text.

- `latency_p50_s` / `latency_p90_s`: time from the full clip being available to the final transcript. All 7 models are non-streaming, so this is the end-of-speech-to-final latency.
- `rtf`: total processing time ÷ total audio time. Below 1 means faster than real time.
- `peak_rss_mb`: peak resident memory of that model's process.
- `max_temp_c`: hottest thermal zone during the run. A rise toward the throttle point makes later numbers worse.

Sanity check: QuartzNet15x5 should score about 4–6% WER. If it's much higher, the hand-written NeMo feature extraction doesn't match the model.
