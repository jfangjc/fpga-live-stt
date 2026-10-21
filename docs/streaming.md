# Microphone streaming

`moonshine.live` keeps the model loaded and captures 16 kHz mono audio from the
PL microphone FIFO. It detects speech and sends revisable partials, then a
final for each utterance. Small and Tiny use the same path. Measured results
are in [RESULTS.md](../RESULTS.md), steps 5 to 8.

## Build the microphone image

The `asr-v3-mic-select` image keeps the 100 MHz bulk engine (1024x1024 tiles)
and adds a selectable data input and I2S slot. Sources:
- `scripts/project_streaming.tcl`
- `rtl/experimental/moonshine_stream_top.v`
- `rtl/experimental/voice_axi_streaming.v`
- `rtl/experimental/sph0645_stream_rx.v`

`project_streaming.tcl` creates the Vivado project in `build/fpga-streaming`
and refuses to overwrite an existing one.

```sh
vivado -mode batch -source scripts/project_streaming.tcl \
  -log build/streaming-vivado.log -journal build/streaming-vivado.jou -tclargs build
python scripts/package_streaming.py --out build/mic-select --bootgen /path/to/bootgen
dtc -@ -I dts -O dtb -o build/mic-select/asr-v3-mic-select.dtbo build/mic-select/asr-v3-mic-select.dts
python scripts/package_streaming.py --out build/mic-select --finalize
```

- **Build gates:** positive setup slack, non-negative hold slack and no DRC
  errors. Timing reports go to `reports/local/streaming-hardware/`.
- **Windows:** pass Vivado's `bin/bootgen.bat` as `--bootgen`.
- **Output:** `--finalize` writes `manifest.json`. The board wrapper checks the
  installed files against it.
- **Previous build:** the build record is in `build/streaming-firmware/`.

Install the `.bit.bin`, `.dtbo` and `shell.json` into
`/lib/firmware/xilinx/asr-v3-mic-select/`.

Capture simulation, which creates its project in `build/streaming-capture-sim`:

```sh
vivado -mode batch -source scripts/streaming_capture_sim.tcl
```

## Select the microphone

Build the FIFO reader on the board:

```sh
sh scripts/build_moonshine_capture.sh
```

| Signal group | WS/LRCLK | DATA | BCLK |
|---|---|---|---|
| Primary | B10 | E12 | D11 |
| Secondary | H12 | E10 | D10 |

| `--mic-select` | Data input | I2S slot | Live options |
|---|---|---|---|
| 0 | Primary | Left | `--mic-input primary --mic-channel left` |
| 1 | Primary | Right | `--mic-input primary --mic-channel right` |
| 2 | Secondary | Left | `--mic-input secondary --mic-channel left` |
| 3 | Secondary | Right | `--mic-input secondary --mic-channel right` |

On the test carrier, J2 is mic L and J3 is mic R. J3 is on select 1. The
microphone's SELECT pin sets the slot. To check a setup:

```sh
sudo env PYTHONPATH=software .venv-moonshine/bin/python scripts/run_moonshine_board.py \
  --app asr-v3-mic-select --hardware-manifest build/mic-select/manifest.json \
  --driver drivers/bulk/qn_tile.ko --evidence reports/local/mic-session.json -- \
  .venv-moonshine/bin/python -m moonshine.capture --seconds 5 --mic-select 1 \
  --out-dir reports/local/mic-right
```

It saves a 24-bit WAV and `capture.json`. Check `transport_passed` and
`signal_present`. All-zero samples mean the wrong slot or wiring. Listen to the
WAV to confirm.

## Live transcription

Export the native decoder (and, for Tiny's modes below, the encoder) as in
[moonshine.md](moonshine.md). Then, for Small:

```sh
sudo env PYTHONPATH=software OMP_WAIT_POLICY=PASSIVE \
  .venv-moonshine/bin/python scripts/run_moonshine_board.py \
  --app asr-v3-mic-select --hardware-manifest build/mic-select/manifest.json \
  --driver drivers/bulk/qn_tile.ko --evidence reports/local/live-session.json -- \
  .venv-moonshine/bin/python -m moonshine.live --size small --backend fpga \
  --ort-decoder build/small-decoder --ort-encoder build/small-encoder \
  --mic-input primary --mic-channel right --vad-dbfs -50 --display text \
  --out reports/local/live-small.jsonl
```

- **Starting:** wait for `Listening for speech` before talking.
- **Stopping:** Ctrl+C ends the session. The wrapper then restores the
  starting FPGA app.
- **Other inputs:**
  - `--capture-seconds 20` records for a fixed time.
  - `--wav clip.wav` replays a file at real-time pace.
  - `--unpaced` is for correctness tests only.
- **Events:** the JSONL log records ready, levels, `audio-health`, utterance
  starts, partials, finals, errors and a summary.
  - Only `final` text is committed.
  - `incomplete` means the decoder hit its token limit.

Default updates are 2.5 s for Small and 1 s for Tiny.

Speech detection is energy-based. Defaults:

| Setting | Default | Option |
|---|---:|---|
| Onset threshold | −55 dBFS | `--vad-dbfs` |
| Onset time | 60 ms | `--attack-ms` |
| Pre-roll | 300 ms | `--pre-roll-ms` |
| Minimum speech | 200 ms | `--min-speech-ms` |
| Silence endpoint | 700 ms | `--silence-ms` |
| Maximum utterance | 12 s | `--max-seconds` |
| DC high-pass | 30 Hz mic, off for WAV | `--highpass-hz` (0 disables, up to 200) |
| Gain to the model | 1 | `--gain` |

- **Capture:** the helper reads the 1024-sample FIFO in 20 ms blocks into a
  10 s queue (`--buffer-seconds`).
- **Errors:** FIFO drops, packet gaps, stalls or a full queue stop the session.

## Tiny low-latency profile

```sh
PYTHONPATH=software .venv-moonshine/bin/python -m moonshine.ort_encoder --size tiny --out build/tiny-encoder

.venv-moonshine/bin/python -m moonshine.live --size tiny --backend fpga \
  --low-latency --ort-decoder build/tiny-decoder --ort-encoder build/tiny-encoder \
  --mic-input primary --mic-channel right --vad-dbfs -50 --display text \
  --out reports/local/live-tiny-latency.jsonl
```

Run `moonshine.live` inside the board wrapper, as above. The profile settings:
- 250 ms updates, a 350 ms endpoint and 3 s contexts;
- two Torch threads and four native threads;
- queued partials are skipped to catch up.

The short context can split words. `--max-seconds 4` keeps more context.

Summarize timing, and check a paced replay against the oracle:

```sh
.venv-moonshine/bin/python scripts/report_moonshine_latency.py \
  reports/local/live-tiny-latency.jsonl --out reports/local/tiny-latency.json
PYTHONPATH=software .venv-moonshine/bin/python scripts/verify_moonshine_live.py \
  clip.wav reports/local/live-tiny-latency.jsonl \
  --ort-decoder build/tiny-decoder --ort-encoder build/tiny-encoder \
  --out reports/local/tiny-latency-oracle.json
```

The report has two timing measures:
- `lag_ms`: emission time relative to the latest captured block.
- `oldest_update_age_ms`: also includes the audio collected for the update and
  the encoder's 240 ms lookahead.

The verifier replays the logged update boundaries through the integer oracle.

## Tiny accuracy mode

Use `--accuracy` instead of `--low-latency`. This mode:
- keeps up to 12 s of encoded speech;
- sends 2 s overlapping previews every 400 ms;
- re-decodes the whole phrase for the final.

Phrase endings:
- a 700 ms silence ends short phrases;
- after 6 s, a 250 ms pause ends the phrase;
- the hard limit is 12 s. A forced boundary carries up to 1 s of audio into the
  next phrase.

Overrides:
- timing: `--preview-seconds`, `--preview-overlap-seconds`, `--chunk-ms`;
- phrase boundaries: `--pause-after-seconds`, `--pause-ms`, `--silence-ms`,
  `--max-seconds`, `--overlap-ms`.

Events:
- `partial` is a preview and may change.
- `final-pending` means the phrase ended but refinement is still running.
- `final` with `refined: true` replaces all previews for its `utterance_id`.
  Finals can arrive after the next phrase's previews.

Up to four refinements can be pending. Past that, the session stops instead of
dropping finals. Overlapping words between phrases are trimmed by text matching:
- `raw_text` keeps the untrimmed output;
- `overlap_uncertain` marks a failed match.

## Measure WER

Write a manifest of mono 16 kHz clips with human transcripts. Clips can be up
to 30 s, and paths are relative to the manifest:

```json
{
  "dataset": "General conversation with human reference transcripts",
  "clips": [{"wav": "conversation.wav", "text": "The exact words spoken in this recording."}]
}
```

```sh
PYTHONPATH=software .venv-moonshine/bin/python -m moonshine.accuracy \
  references.json --live-events reports/local/live-tiny-accuracy.jsonl \
  --out reports/local/live-tiny-accuracy-wer.json
PYTHONPATH=software .venv-moonshine/bin/python -m moonshine.accuracy \
  references.json --variant fpga-int8 --size tiny \
  --ort-decoder build/tiny-decoder --ort-encoder build/tiny-encoder \
  --out reports/local/tiny-int8-wer.json
```

- **What is scored:** final captions only, ignoring case and punctuation.
- **Variants:** `float`, `fpga-int8`, `fpga-float-attention` and
  `fpga-float-decoder`.
- **Board:** run the FPGA variants inside the board wrapper.
