"""Create a separate scheduling confirmation harness from the measured benchmark."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'software/ort_fpga_shortcache/benchmark.py').read_text()
def replace(old,new):
    global text
    assert old in text,old
    text=text.replace(old,new)
replace('from graph import candidate',"runtime=ROOT/'software/ort_fpga_shortcache'\nsys.path.insert(0,str(runtime))\nfrom graph import candidate\nfrom dma_irq import snapshot,configure")
replace("a=ap.parse_args();assert a.runs>=20", "a=ap.parse_args();assert a.runs>=300\n    policy_path=ROOT/'reports/fused/shortcache_schedule_screen.json'\n    policy=json.loads(policy_path.read_text())\n    assert policy['complete'] and policy['hardware_execution'] and not policy['timing_acceptance']\n    policies={r['context_seconds']:r for r in policy['selected']}")
replace("library=Path(__file__).with_name('libort_fpga.so')", "library=runtime/'libort_fpga.so'")
replace('rng=random.Random(11102026)', 'rng=random.Random(1110202602)')
replace("rows=[];summaries=[];startup={}", "rows=[];summaries=[];startup={};irq_before=snapshot()\n    assert policy['library_sha256']==sha(library) and policy['cpu_model_sha256']==sha(cpu_path)\n    assert policy['graph_source_sha256']==sha(runtime/'graph.py') and policy['selection_sha256']==sha(runtime/'selection.json')")
replace('spin=10 if seconds>=1 else 0', "cfg=policies[seconds];configure(cfg['dma_irq_core'])\n            cpu_spin=cfg['cpu_spin_duration_us'];fpga_spin=cfg['fpga_spin_duration_us']")
replace('def session(g,physical):', 'def session(g,physical):\n                spin=fpga_spin if physical else cpu_spin')
replace("'physical_oracle_bit_parity':True,'spin_duration_us':spin,", "'physical_oracle_bit_parity':True,'cpu_spin_duration_us':cpu_spin,\n                     'fpga_spin_duration_us':fpga_spin,'dma_irq_core':cfg['dma_irq_core'],'dma_irq_affinity':snapshot(),")
replace("summaries.append(summary);print(json.dumps(summary),flush=True);del runners", "summaries.append(summary);print(json.dumps({k:summary[k] for k in ('context_seconds','cpu_p50','fpga_p50','cpu_p95','fpga_p95','mean_saving_95ci_seconds','cpu_spin_duration_us','fpga_spin_duration_us','dma_irq_core')}),flush=True);del runners")
replace("finally:os.sched_setaffinity(0,before_affinity)", "finally:\n        os.sched_setaffinity(0,before_affinity)\n        for irq,value in irq_before.items():(Path('/proc/irq')/irq/'smp_affinity_list').write_text(value['requested'])\n        assert {i:v['requested'] for i,v in snapshot().items()}=={i:v['requested'] for i,v in irq_before.items()}")
replace("'runtime':'shortcache'", "'runtime':'shortcache-scheduled'")
replace("sha(Path(__file__).with_name('graph.py'))", "sha(runtime/'graph.py')")
replace("'startup':startup,'contexts':summaries", "'startup':startup,'policy_sha256':sha(policy_path),'dma_irq_core':summaries[0]['dma_irq_core'],\n                     'irq_before':irq_before,'irq_after':snapshot(),'fpga_threads':4,'contexts':summaries")
(ROOT/'software/latency/confirm_short_cache_schedule.py').write_bytes(text.encode())
print('Created separate 300-run scheduling confirmation harness')
