"""Screen longer ORT spin windows fairly on CPU and the new FPGA image."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'software/latency/tune_tail_cpu.py').read_text()
start=text.index('policies=[');end=text.index('frontend=',start)
text=text[:start]+'''policies=[{'graph':'boundary','threads':4,'spin':10,'level':'extended'}]
policies += [{'graph':'tail','threads':4,'spin':spin,'level':level} for spin in (10,100,500,1000) for level in ('extended','all')]
'''+text[end:]
(ROOT/'software/latency/tune_tail_cpu_spin.py').write_text(text)
text=(ROOT/'software/latency/tune_prefetch_tail_policy.py').read_text()
text=text.replace('tail_cpu_policy.json','tail_cpu_spin_policy.json')
start=text.index('policies=[');end=text.index('random.Random',start)
text=text[:start]+'''policies=[{'threads':4,'spin':spin,'level':'extended','irq_core':irq} for spin in (10,100,500,1000) for irq in (0,3)]
policies += [{'threads':4,'spin':spin,'level':'all','irq_core':3} for spin in (10,500)]
'''+text[end:]
(ROOT/'software/latency/tune_prefetch_spin_policy.py').write_text(text)
