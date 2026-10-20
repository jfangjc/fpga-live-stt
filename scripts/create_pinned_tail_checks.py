"""Generate paired checks of the combined, already separately verified operators."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for name in ('validate_tail_physical.py','tune_tail_policy.py','confirm_tail_latency.py'):
    text=(ROOT/'software/latency'/name).read_text().replace('from tail_benchmark import','from pinned_tail_benchmark import')
    if name=='tune_tail_policy.py':
        start=text.index('policies=[');end=text.index('random.Random',start)
        text=text[:start]+'''policies=[{'threads':4,'spin':10,'level':level,'irq_core':irq,'res_threads':res}
          for level,irq,res in (('extended',0,3),('all',0,3),('extended',3,3),('all',3,3),('all',3,4))]
'''+text[end:]
    (ROOT/'software/latency'/name.replace('tail_','pinned_tail_')).write_text(text)
