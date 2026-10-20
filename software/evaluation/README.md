# Paired CPU/FPGA evaluation

`benchmark.py` keeps a CPU runner and an FPGA runner initialized side by side.
It warms both, alternates their order with a seeded shuffle and times each
complete `transcribe` call. Initialization is reported separately. It also
records CPU frequency and temperatures around every call, and reports
per-clip medians, p50/p95 and corpus WER.

A runner module provides `create_runner(mode, threads)`, which returns an object
with these methods:
- **`metadata()`:** model, tokenizer, preprocessing and decoder identity,
  precision, thread count and `hardware_execution`.
- **`transcribe(audio_path)`:** returns `{"transcript": ...}`.
- **`close()`.**

A FPGA call has to report positive LOAD, RUN and ioctl counts.

The manifest is JSON Lines, one record per held-out recording:

```json
{"id":"quiet_001","audio":"audio/quiet_001.wav","text":"reference transcript","split":"evaluation","categories":["quiet","names"]}
```

```sh
python -m unittest -v test_evaluation.py
python benchmark.py --adapter citrinet_adapter --manifest heldout.jsonl --threads 4 --warmups 3 --repeats 20 --pl-clock-hz 100000000 --out kv260_paired.json
python evaluate_corpus.py --manifest ../../research/eval/librispeech-mini/evaluation.jsonl --mode fpga --output mini_wer.json
```

WER normalization uses Unicode NFKC, lowercase and punctuation removal, and
keeps apostrophes. `../../verification/evaluate_gates.py` applies the
acceptance gates to the benchmark output.
