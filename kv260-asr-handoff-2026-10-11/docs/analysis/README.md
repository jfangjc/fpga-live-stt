# Analysis scripts

Every number tagged **[C]** (computed) in `../ARCHITECTURE_REVIEW.md` and `../DECISIONS.md` comes from these two scripts. They use only the Python standard library.

```bash
cd docs/analysis
python3 costmodel.py ../../../research/checkpoints/citrinet-256-ls/model_config.yaml citrinet_layers.json
python3 estimates.py citrinet_layers.json
```

- `costmodel.py` parses the Citrinet-256 checkpoint config and builds a per-layer MAC/weight/frame-rate table. It also builds the QuartzNet 5x5/15x5 tables from the QuartzNet paper's Table 1. As a check, it reproduces the snapshot's own census exactly: 2,732,405,760 conv MACs and 2,572,303,104 pointwise MACs at 1,008 frames (`research/README.md`), and 6.69 M QuartzNet 5x5 weights against the paper's 6.7 M.
- `estimates.py` holds the Amdahl bounds (using the measured shortwide counters typed in from `reports/fused/shortwide_counter_comparison.json`), the whole-encoder cycle model, the on-chip memory budget, live duty cycles, two-mic array gain/TDOA, mic clock jitter and the emission-latency model.
