"""Keep tail arithmetic unchanged and bind it to the new prefetch image."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'software/latency/tail_benchmark.py').read_text().replace('from chain_benchmark import','from prefetch_benchmark import')
(ROOT/'software/latency/prefetch_tail_benchmark.py').write_text(text)
for name in ('validate_tail_physical.py','tune_tail_policy.py','confirm_tail_latency.py'):
    text=(ROOT/'software/latency'/name).read_text().replace('from tail_benchmark import','from prefetch_tail_benchmark import')
    (ROOT/'software/latency'/name.replace('tail_','prefetch_tail_')).write_text(text)
