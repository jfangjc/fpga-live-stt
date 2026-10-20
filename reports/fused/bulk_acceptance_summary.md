# asr-v3-bulk, three offloaded operators: paired measurements

Physical runs of the 512-MAC `asr-v3-bulk` image at 100 MHz, 10 October 2026.
Each warm call times WAV reading, the frontend, one ORT graph and decoding. The
CPU path is the fastest tested INT8 graph with four non-spinning threads. The
"CI" column is the 95% bootstrap interval of the paired mean saving. Negative
values mean the FPGA path was slower.

## bulk_three_user_acceptance.json (100 pairs)

| Recording | CPU p50 (ms) | FPGA p50 (ms) | CPU p95 (ms) | FPGA p95 (ms) | CI (ms) | CPU/FPGA errors |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| user-speech-original | 536.924 | 532.440 | 552.568 | 545.094 | 4.493 to 10.305 | 4/4 |

## bulk_three_corpus_acceptance.json (50 pairs per recording)

| Recording | CPU p50 (ms) | FPGA p50 (ms) | CPU p95 (ms) | FPGA p95 (ms) | CI (ms) | CPU/FPGA errors |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| user-speech-original | 532.261 | 529.108 | 545.875 | 536.276 | 1.401 to 5.507 | 4/4 |
| 6930-75918-0000 | 241.960 | 244.812 | 257.203 | 262.488 | -7.704 to -1.651 | 0/0 |
| 6930-75918-0001 | 695.306 | 690.120 | 706.547 | 699.816 | 4.529 to 7.589 | 2/2 |
| 6930-75918-0002 | 318.555 | 322.000 | 332.852 | 336.110 | -7.464 to -0.477 | 0/0 |
| 6930-75918-0003 | 1083.533 | 1072.805 | 1095.448 | 1083.007 | 9.568 to 13.717 | 1/1 |
| 6930-75918-0004 | 582.636 | 570.633 | 675.918 | 649.412 | 8.833 to 14.922 | 1/1 |
| user-ac-quiet-minus20db | 534.483 | 528.459 | 544.141 | 539.059 | 3.246 to 7.453 | 5/5 |
| user-ac-noise-snr20 | 534.007 | 531.357 | 548.311 | 539.716 | 1.756 to 7.152 | 4/4 |
| user-ac-noise-snr10 | 532.747 | 529.615 | 545.884 | 536.145 | 3.133 to 6.627 | 7/7 |

Total word errors: CPU 24/269, FPGA 24/269.

## bulk_three_original_reference.json (50 pairs)

| Recording | CPU p50 (ms) | FPGA p50 (ms) | CPU p95 (ms) | FPGA p95 (ms) | CI (ms) | CPU/FPGA errors |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| original-reference-regression | 414.248 | 412.252 | 427.534 | 424.132 | 1.642 to 5.958 | 0/0 |

The reference transcript for this clip is an earlier model prediction, not a
human transcript.

## Retest of the saved revision

| Recording | CPU p50/p95 (s) | FPGA p50/p95 (s) | CI (ms) |
| --- | --- | --- | --- |
| user-speech-original | 0.534222/0.543708 | 0.528827/0.538152 | 3.362 to 8.084 |
| original-reference-regression | 0.413088/0.424692 | 0.412546/0.419427 | 0.275 to 3.983 |
| original-reference, idle-board repeat | 0.414314/0.428422 | 0.417216/0.427448 | -1.894 to 2.616 |

The first reference retest may have overlapped a compile job on the board. The
idle-board repeat was slower on the FPGA path, so the gain on that clip is not
reliable.
