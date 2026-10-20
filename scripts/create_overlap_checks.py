"""Keep overlap validation/benchmarks separate from the qualified chain version."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];directory=ROOT/'software/latency'
for old,new in (('validate_chain_physical.py','validate_overlap_physical.py'),
                ('tune_chain_policy.py','tune_overlap_policy.py'),('confirm_chain_latency.py','confirm_overlap_latency.py')):
    source=(directory/old).read_text().replace('from chain_benchmark import *','from overlap_benchmark import *')
    if old=='validate_chain_physical.py':
        source=source.replace("'physical_counters':physical['counters']","'physical_counters':physical['counters'],'overlap_counters':physical['overlap_counters']")
    if old=='tune_chain_policy.py':
        begin=source.index('policies=[');end=source.index('random.Random(20261012).shuffle(policies)',begin)
        source=source[:begin]+'''policies=[{'threads':4,'spin':s,'level':level,'irq_core':irq}
          for s,level,irq in ((10,'all',0),(10,'all',3),(0,'all',0),(0,'all',3),(10,'extended',0),(10,'extended',3))]
'''+source[end:]
    (directory/new).write_text(source)
print('Created separate overlap physical/policy/confirmation harnesses')
