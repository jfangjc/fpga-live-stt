"""Independently audit fresh paired measurements and their physical bindings."""
import hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
rows=[];sources={}
for label in ('half','one'):
    path=ROOT/f'reports/fused/shortcache_scheduled_{label}.json';proof=read(path)
    assert proof['complete'] and proof['hardware_execution'] and proof['runs']==300
    for name,key in [('software/latency/confirm_short_cache_schedule.py','source_sha256'),
                     ('reports/fused/shortcache_schedule_screen.json','policy_sha256'),
                     ('reports/fused/shortcache_physical_validation.json','validation_sha256'),
                     ('software/ort_fpga_shortcache/libort_fpga.so','library_sha256'),
                     ('deployment/experimental-shortcache/qn_tile.ko','driver_sha256'),
                     ('deployment/asr-v3-shortcache/asr-v3-shortcache.bit.bin','firmware_sha256')]:
        assert sha(ROOT/name)==proof[key],name
    assert sha(path.with_suffix('.onnx'))==proof['fpga_graph_sha256']
    assert proof['irq_before']==proof['irq_after']
    context=proof['contexts'][0];pairs=proof['paired_runs'];assert len(pairs)==300
    for pair in pairs:
        cpu,fpga=pair['results']['cpu'],pair['results']['fpga']
        assert cpu['text']==fpga['text'] and cpu['length']==fpga['length']
        counts=fpga['counters'];assert counts['physical_calls']==32 and counts['ioctls']==32 and counts['loads']==0 and counts['oracle_calls']==0
    c=np.array([p['results']['cpu']['seconds'] for p in pairs]);f=np.array([p['results']['fpga']['seconds'] for p in pairs])
    ci=np.percentile(np.random.default_rng(11102026).choice(c-f,(10000,len(c)),replace=True).mean(axis=1),[2.5,97.5])
    values={'cpu_p50':np.median(c),'fpga_p50':np.median(f),'cpu_p95':np.percentile(c,95),'fpga_p95':np.percentile(f,95)}
    for key,value in values.items():assert abs(context[key]-value)<1e-12
    np.testing.assert_allclose(ci,context['mean_saving_95ci_seconds'],rtol=0,atol=1e-12)
    assert f.size==300 and ci[0]>0 and values['fpga_p50']<values['cpu_p50'] and values['fpga_p95']<values['cpu_p95']
    rows.append(dict(context_seconds=context['context_seconds'],**{k:float(v) for k,v in values.items()},
                     gain_percent=float(100*(1-np.median(f)/np.median(c))),mean_saving_95ci_seconds=ci.tolist(),
                     cpu_spin_duration_us=context['cpu_spin_duration_us'],fpga_spin_duration_us=context['fpga_spin_duration_us'],
                     dma_irq_core=context['dma_irq_core']))
    sources[path.relative_to(ROOT).as_posix()]=sha(path)
resident=ROOT/'reports/fused/shortcache_scheduled_resident_validation.json';api=read(resident)
assert api['complete'] and api['hardware_execution'] and len(api['calls'])==20
assert api['resident_source_sha256']==sha(ROOT/'software/latency/short_cache_scheduled_resident.py')
assert api['accepted_resident_source_sha256']==sha(ROOT/'software/latency/resident.py')
restore=ROOT/'reports/fused/shortcache_scheduled_board_restoration.json';assert read(restore)['complete']
sources[resident.relative_to(ROOT).as_posix()]=sha(resident);sources[restore.relative_to(ROOT).as_posix()]=sha(restore)
summary={'complete':True,'hardware_execution':True,'whole_model_latency_accepted':True,
         'ten_percent_latency_accepted':all(r['gain_percent']>=10 for r in rows),'contexts':rows,
         'evidence_sha256':sources,'representative_corpus_qualified':False,'capture_tested':False}
(ROOT/'reports/fused/shortcache_scheduled_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
table=['| Input | CPU p50 / p95 | FPGA p50 / p95 | p50 reduction |','| --- | --- | --- | --- |']
for r in rows:table.append(f"| {r['context_seconds']:g} s | {r['cpu_p50']*1000:.3f} / {r['cpu_p95']*1000:.3f} ms | {r['fpga_p50']*1000:.3f} / {r['fpga_p95']*1000:.3f} ms | {r['gain_percent']:.2f}% |")
(ROOT/'SHORT_CACHE_SCHEDULE_RESULTS.md').write_text('\n'.join([
    '# Confirmed short-input FPGA scheduling', '',*table,'',
    'Each input has 300 fresh randomized paired warm measurements. Timings include the audio frontend, model, all warm transfers and decoding. CPU uses the fastest screened valid four-thread policy (10 us spin). FPGA uses 10 us spin / IRQ core 0 at 0.5 s and no spin / IRQ core 3 at 1 s.', '',
    'Both p50 and p95 improve; paired mean-saving confidence intervals remain above zero. The 10% target is not yet met. The graph accelerates 32 retained pairs (64 convolutions) and performs 32 ioctls with zero warm weight loads.', '',
    'Physical logits match the INT8 oracle; diagnostic prefix transcripts and lengths match CPU. The separate scheduled resident API passed 20 warm calls. Accepted bulk firmware, driver, clock and IRQ masks were restored. Representative corpus accuracy and live capture remain unqualified.', '',
    'Next experiment: widen depthwise time parallelism from 16 to 64 lanes while preserving 512 pointwise MACs, the 100 MHz clock, graph selection and arithmetic. Its performance remains unproven.'
])+'\n')
print(json.dumps(summary))
