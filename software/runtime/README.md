# First runtime

`citrinet_adapter.py` runs the exported Citrinet-256 graph with its 80-mel
frontend and WordPiece CTC decoder. It has three modes:

| Mode | What runs |
|---|---|
| `cpu` | The whole optimized ORT graph, with an explicit thread count |
| `emulate` | The FPGA partition, with each offloaded layer computed by the numerical INT8 model |
| `fpga` | The 126 eligible 1x1 convolutions on the FPGA through `../native/libqnc`; everything else in 127 resident ORT CPU regions |

This design was slower than CPU only. [RESULTS.md](../../RESULTS.md) section 1
explains why.

```sh
python -m unittest -v test_partition.py test_output_parity.py
python citrinet_adapter.py /path/to/clip.wav --mode cpu --threads 4 --runs 3
python validate_outputs.py /path/to/clip.wav --mode fpga --output hardware_output.json
python citrinet_adapter.py /path/to/clip.wav --mode fpga --threads 4 --runs 3
```

`validate_outputs.py --mode fpga` passes only if the physical output matches the
numerical INT8 graph on the same features. `profile_cpu_regions.py` times the CPU
regions without using the FPGA.

Set `CITRINET_MODEL_DIR` and `QNC_DEVICE` to use other paths.
