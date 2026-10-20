# Verification

These are independent checks, written separately from the runtime code they
audit.

| Script | Checks |
|---|---|
| `audit_existing.py` | Hashes and wire lengths of the earlier QuartzNet prototype, recomputed from its layer shapes |
| `audit_model.py` | The exported ONNX graph against the pinned NeMo Jasper components, over random lengths and masks |
| `audit_runtime.py` | The runtime frontend against a Torch reference |
| `audit_native_neon.py` | The NEON and scalar `libqnc` builds |
| `audit_v2_hardware.py` | The generated block design and device tree: DMA width, register addresses and IRQ lanes; also routed report freshness |
| `board_profile_analysis.py` | Maps a board profile back to the 253 CPU and FPGA steps of the first v2 runtime |
| `experiment_board_audit.py`, `fallback_board_audit.py` | Recomputes percentiles and checks source bindings in the board reports |
| `evaluate_gates.py` | Acceptance gates on a paired benchmark: latency, WER and capture drops |
| `test_mvp.py`, `test_mvp_runner.py` | MVP input bounds, error propagation and release integrity; the board runner's control flow against fake board commands |
| `collect_evidence.py` | Builds the provenance file that `evaluate_gates.py` requires, from real report files |

Each script writes its results to a matching `*.json` file in this directory.
The `*-vectors/`, `adaptive-dw/`, `bimodal-dw/`, `exact-requant/` and
`wrapped-requant/` folders hold test vectors for the RTL testbenches.

```sh
python verification/test_gates.py
python verification/test_collect_evidence.py
python verification/evaluate_gates.py benchmark.json --benchmark-evidence provenance.json --output gates.json
```

`evaluate_gates.py` exits with:
- **0** if every gate passes;
- **1** if a measured gate fails;
- **2** if the evidence is missing or inconsistent.

The gates use the WER normalization in `software/evaluation/benchmark.py`. They
require a corpus that covers quiet speech, accents, numbers, names and noise.
No such corpus was collected, so none of the final gates have been run.
