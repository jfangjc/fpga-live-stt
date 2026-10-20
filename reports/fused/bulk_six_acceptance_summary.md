# asr-v3-bulk, six offloaded operators: paired measurements

Physical runs of the 512-MAC `asr-v3-bulk` image at 100 MHz, 10 October 2026.
50 randomized pairs per recording against the matched four-thread CPU INT8
graph. Each call times WAV reading, the frontend, inference and decoding. The
"CI" column is the 95% interval of the paired mean saving.

| Recording | CPU p50/p95 (s) | FPGA p50/p95 (s) | CI (ms) |
| --- | --- | --- | --- |
| user-speech-original | 0.539594/0.568092 | 0.530034/0.547604 | 4.395 to 16.677 |
| 6930-75918-0000 | 0.240432/0.261219 | 0.243117/0.259361 | -4.527 to 2.389 |
| 6930-75918-0001 | 0.705891/0.715012 | 0.684725/0.697422 | 18.250 to 22.254 |
| 6930-75918-0002 | 0.313308/0.328504 | 0.310946/0.327139 | 0.505 to 6.472 |
| 6930-75918-0003 | 1.098613/1.105283 | 1.073488/1.086465 | 22.044 to 26.188 |
| 6930-75918-0004 | 0.584714/0.594714 | 0.569052/0.581245 | 12.052 to 16.394 |
| user-ac-quiet-minus20db | 0.536649/0.549765 | 0.529705/0.543077 | 5.161 to 9.658 |
| user-ac-noise-snr20 | 0.538285/0.549732 | 0.528422/0.537322 | 8.166 to 11.867 |
| user-ac-noise-snr10 | 0.535666/0.547486 | 0.527941/0.535185 | 7.824 to 11.621 |

- Eight of nine recordings save time. The shortest clip is slower at the median
  and its interval crosses zero.
- All physical outputs match the integer oracle exactly.
- Both paths make 24/269 word errors. The SNR20 variant differs by one
  misspelled token.

Independent confirmations, 100 pairs each with three warmups:

| Recording | CPU p50/p95 (s) | FPGA p50/p95 (s) | CI (ms) |
| --- | --- | --- | --- |
| user-speech-original | 0.535780/0.545946 | 0.528802/0.540144 | 5.242 to 8.263 |
| original-reference-regression | 0.414522/0.426969 | 0.409007/0.422607 | 4.895 to 8.318 |

Run the matched graph in one resident session on the board (root access to
`/dev/qn-tile` and the `asr-v3-bulk` image and driver are required):

```sh
python software/ort_fpga_bulk/transcribe.py --benchmark reports/fused/bulk_six_user_acceptance.json --wav /path/to/clip.wav
```

Add `--cpu` to run the CPU baseline. The first call includes cold weight setup.
