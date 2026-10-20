"""Isolated tail qualification, policy screen and independent confirmation."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'software/latency/validate_chain_physical.py').read_text().replace('from chain_benchmark import','from tail_benchmark import')
(ROOT/'software/latency/validate_tail_physical.py').write_text(text)
text=(ROOT/'software/latency/tune_chain_policy.py').read_text().replace('from chain_benchmark import','from tail_benchmark import')
start=text.index("cpu_config={'threads'");end=text.index('policies=[',start)
text=text[:start]+'''cpu_config={'threads':4,'spin':10,'level':'extended'}
cpu_screen_path=ROOT/'reports/fused/tail_cpu_policy.json'
cpu_screen=json.loads(cpu_screen_path.read_text());assert cpu_screen['complete'] and cpu_screen['all_logits_bit_exact']
assert cpu_screen['model_sha256']==sha(items['model']) and cpu_screen['residual_tail_library_sha256']==sha(items['tail_library'])
cpu_policies={str(c['context_seconds']):c['selected']['policy'] for c in cpu_screen['contexts']}
'''+text[end:]
text=text.replace("cpu=make_session(items['cpu'],cpu_config,[items['boundary_library']])", "cpu_runners={s:make_session(cpu_graph(items,c),c,[items['boundary_library']]) for s,c in cpu_policies.items()}")
text=text.replace('for seconds in (.5,1,2.5):',"for seconds in (.5,1,2.5):\n        cpu=cpu_runners[str(seconds)]",1)
needle='        for seconds in (.5,1,2.5):'
text=text.replace(needle,needle+"\n            cpu=cpu_runners[str(seconds)]")
text=text.replace("'cpu_policy':cpu_config,'policies':", "'cpu_policies':cpu_policies,'policies':")
(ROOT/'software/latency/tune_tail_policy.py').write_text(text)
text=(ROOT/'software/latency/confirm_chain_latency.py').read_text().replace('from chain_benchmark import','from tail_benchmark import')
text=text.replace("cpu=make_session(items['cpu'],screen['cpu_policy'],[items['boundary_library']])", 'cpu=None')
text=text.replace("seconds=selected['context_seconds'];config=selected['policy'];configure(config['irq_core'])", "seconds=selected['context_seconds'];config=selected['policy'];configure(config['irq_core'])\n        cpu_policy=screen['cpu_policies'][str(seconds)]\n        cpu=make_session(cpu_graph(items,cpu_policy),cpu_policy,[items['boundary_library']])")
text=text.replace("screen['cpu_policy']",'cpu_policy')
text=text.replace("for key in ('firmware_sha256','library_sha256','boundary_library_sha256','cpu_model_sha256'):", "for key in ('firmware_sha256','library_sha256','boundary_library_sha256','cpu_model_sha256','residual_tail_library_sha256'):")
(ROOT/'software/latency/confirm_tail_latency.py').write_text(text)
print('Created isolated common-tail checks')
