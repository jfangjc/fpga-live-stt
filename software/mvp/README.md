# kv260-asr-mvp: Citrinet WAV transcriber

`transcribe.py` transcribes one short WAV with the final
`asr-v3-branch512-ab166` design. Input must be uncompressed 16 kHz mono PCM16,
PCM24 or PCM32 with 320 to 40,959 samples (0.02 to 2.56 s). Audio is never
truncated, resampled or split.

## Board prerequisites

- KV260 on Ubuntu 24.04, kernel `6.8.0-1036-xilinx`, with `xmutil` and the
  `asr-v3-bulk` app working at 100 MHz.
- Drivers built for the running kernel: the branch driver at
  `deployment/experimental-stream-branch/qn_tile.ko` and the bulk rollback
  driver at `deployment/kernel-compat/<kernel>/bulk/qn_tile.ko`.
- The release manifest `release/MVP_MANIFEST.json`, written by
  `scripts/package_mvp.py`. `scripts/package_mvp_runtime.py` then makes the
  smaller board-only archive.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r software/requirements-runtime.txt
.venv/bin/python scripts/verify_mvp.py --manifest release/MVP_MANIFEST.json
sudo .venv/bin/python scripts/install_branch512_ab166_firmware.py
```

The installer refuses to overwrite an existing app.

## Transcribe

```sh
sudo sh scripts/run_mvp_board.sh software/mvp/transcribe.py /absolute/path/clip.wav --out reports/mvp/transcript.json
```

- The runner checks the kernel, both drivers and the installed firmware before
  changing anything. It then switches to the branch app and always restores the
  bulk app, its 100 MHz clock, driver and DMA IRQ masks, even on failure or
  Ctrl-C. Before/after states go to `reports/mvp/bulk_before_*.json` and
  `bulk_restored_*.json`.
- The output JSON holds the text, frame count, stage times, session setup time,
  FPGA counters and artifact hashes. Pick a new output path each time.
- `--policy-context 0.5`, `1` or `2.5` picks a saved CPU-thread policy; by
  default the nearest duration is used.
- Session setup takes about 109 s. A cold call makes 48 ioctls (24
  registrations and 24 runs); warm calls make 24.

If restoration fails: reload `asr-v3-bulk`, set its clock to 100000000, insert
the bulk rollback driver and compare the IRQ masks with the before-report.

## Reproduce the warm benchmark

Copy the original test recording to `research/eval/user-recording/speech.wav`
first (recordings are not committed):

```sh
sudo sh scripts/run_mvp_board.sh software/latency/confirm_branch512_ab166_vf_latency.py --policy reports/fused/branch512_ab166_vf_latency_policy.json --runs 300 --out reports/mvp/board_confirmation.json
.venv/bin/python scripts/audit_branch512_ab166_combined.py --variant vf --report reports/mvp/board_confirmation.json --out reports/mvp/board_acceptance.json
```

## Host checks (Windows)

```powershell
py -I verification/test_mvp.py
py -I verification/test_mvp_runner.py
foreach ($suite in 'ab_mac_conformance','branch512_ab_fast_sim','branch512_ab_reset_sim','branch512_ab_payload_reset_sim') {
    & $vivado -mode batch -source scripts/mvp_sim.tcl -tclargs $suite
}
py -I software/latency/validate_valid_frame_frontend.py --out reports/mvp/frontend_validation.json
py -I scripts/verify_mvp.py
```

`$vivado` is the path to `vivado.bat`. The frontend check needs NumPy, ONNX
Runtime and the evaluation recordings. `verify_mvp.py` without `--manifest`
audits the saved evidence and writes `reports/mvp/verification.json`. Results are in
[RESULTS.md](../../RESULTS.md#mvp-packaging-15-october).
