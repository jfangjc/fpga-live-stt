"""Independently audit fresh paired measurements and their physical bindings."""
import hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
rows=[];sources={}
for label in ('half','one'):
    path=ROOT/f'reports/fused/shortwide_scheduled_{label}.json';proof=read(path)
    assert proof['complete'] and proof['hardware_execution'] and proof['runs']==300
    for name,key in [('software/latency/confirm_short_wide_schedule.py','source_sha256'),
                     ('reports/fused/shortcache_schedule_screen.json','policy_sha256'),
                     ('reports/fused/shortwide_physical_validation.json','validation_sha256'),
                     ('software/ort_fpga_shortwide/libort_fpga.so','library_sha256'),
                     ('deployment/experimental-shortwide/qn_tile.ko','driver_sha256'),
                     ('deployment/asr-v3-shortwide/asr-v3-shortwide.bit.bin','firmware_sha256')]:
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
    assert f.size==300
    accepted=bool(ci[0]>0 and values['fpga_p50']<values['cpu_p50'] and values['fpga_p95']<values['cpu_p95'])
    rows.append(dict(context_seconds=context['context_seconds'],**{k:float(v) for k,v in values.items()},
                     latency_accepted=accepted,gain_percent=float(100*(1-np.median(f)/np.median(c))),mean_saving_95ci_seconds=ci.tolist(),
                     cpu_spin_duration_us=context['cpu_spin_duration_us'],fpga_spin_duration_us=context['fpga_spin_duration_us'],
                     dma_irq_core=context['dma_irq_core']))
    sources[path.relative_to(ROOT).as_posix()]=sha(path)
resident=ROOT/'reports/fused/shortwide_scheduled_resident_validation.json';api=read(resident)
assert api['complete'] and api['hardware_execution'] and len(api['calls'])==20
assert api['resident_source_sha256']==sha(ROOT/'software/latency/short_wide_resident.py')
assert api['accepted_resident_source_sha256']==sha(ROOT/'software/latency/resident.py')
restore=ROOT/'reports/fused/shortwide_board_restoration.json';assert read(restore)['complete']
sources[resident.relative_to(ROOT).as_posix()]=sha(resident);sources[restore.relative_to(ROOT).as_posix()]=sha(restore)
firmware=ROOT/'reports/fused/shortwide_firmware_evidence.json';evidence=read(firmware)
assert evidence['complete'] and evidence['setup_slack_ns']>=0 and evidence['hold_slack_ns']>=0
assert evidence['firmware_bin_sha256']==proof['firmware_sha256']
for name,digest in evidence['sources_and_evidence_sha256'].items():assert sha(ROOT/name)==digest,name
synthetic=ROOT/'reports/fused/shortwide_physical_synthetic.json';numeric=read(synthetic)
assert numeric['complete'] and numeric['hardware_execution'] and numeric['exact_numpy_parity']
assert len(numeric['cases'])==240 and all(r['bit_exact'] for r in numeric['cases'])
assert {r['times'] for r in numeric['cases']}=={1,17,33,51,65,101,129,255,256}
physical=read(ROOT/'reports/fused/shortwide_physical_validation.json')
assert physical['complete'] and physical['hardware_execution'] and len(physical['clips'])==36
assert all(r['physical_oracle_bit_parity'] and r['length_exact'] and r['texts']['cpu']==r['texts']['fpga'] for r in physical['clips'])
sources[firmware.relative_to(ROOT).as_posix()]=sha(firmware);sources[synthetic.relative_to(ROOT).as_posix()]=sha(synthetic)
summary={'complete':True,'hardware_execution':True,'whole_model_latency_accepted':all(r['latency_accepted'] for r in rows),
         'ten_percent_latency_accepted':all(r['latency_accepted'] and r['gain_percent']>=10 for r in rows),'contexts':rows,
         'evidence_sha256':sources,'representative_corpus_qualified':False,'capture_tested':False}
(ROOT/'reports/fused/shortwide_scheduled_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
table=['| Input | CPU p50 / p95 | FPGA p50 / p95 | p50 reduction |','| --- | --- | --- | --- |']
for r in rows:table.append(f"| {r['context_seconds']:g} s | {r['cpu_p50']*1000:.3f} / {r['cpu_p95']*1000:.3f} ms | {r['fpga_p50']*1000:.3f} / {r['fpga_p95']*1000:.3f} ms | {r['gain_percent']:.2f}% |")
(ROOT/'SHORT_WIDE_RESULTS.md').write_text('\n'.join([
    '# Wider-depthwise physical FPGA results','',*table,'',
    'Fresh 300-run randomized paired warm measurements per input include frontend, model, decoding and all warm FPGA transfers. CPU uses the fastest screened valid policy. FPGA graph selection, native binary and driver are unchanged; depthwise hardware widened from 16 to 64 time lanes.', '',
    f"Whole-model latency gate: {summary['whole_model_latency_accepted']}. At least 10% p50 reduction on both inputs: {summary['ten_percent_latency_accepted']}.", '',
    '240 isolated arithmetic checks matched independent NumPy exactly, including frame-boundary cases. The 36 diagnostic prefixes matched physical INT8 oracle logits and CPU transcripts/lengths. Warm calls executed 32 retained pairs (64 convolutions), 32 ioctls and zero weight reloads. The resident API and board restoration checks passed.', '',
    'Timing meets 100 MHz. Representative corpus accuracy and live capture remain unqualified; prefix transcripts remain provisional.'
])+'\n')
print(json.dumps(summary))
