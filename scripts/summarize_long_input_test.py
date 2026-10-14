"""Audit longer-window paired measurements separately from accepted short proofs."""
import hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
path=ROOT/'reports/fused/shortwide_long_inputs.json';proof=read(path)
assert proof['complete'] and proof['hardware_execution'] and proof['runs']==100
assert proof['runtime']=='shortwide-long-input-test' and len(proof['paired_runs'])==400
for name,key in [('software/latency/test_short_wide_long_inputs.py','source_sha256'),('reports/fused/shortcache_schedule_screen.json','policy_sha256'),
                 ('research/fused/cpu-int8-cse.onnx','cpu_model_sha256'),('reports/fused/shortwide_physical_validation.json','validation_sha256'),
                 ('software/ort_fpga_shortwide/libort_fpga.so','library_sha256'),('deployment/experimental-shortwide/qn_tile.ko','driver_sha256'),
                 ('deployment/asr-v3-shortwide/asr-v3-shortwide.bit.bin','firmware_sha256')]:assert sha(ROOT/name)==proof[key],name
assert sha(path.with_suffix('.onnx'))==proof['fpga_graph_sha256']
assert proof['irq_before']==proof['irq_after'] and proof['cpu_threads']==4
rows=[]
for context in proof['contexts']:
    pairs=[r for r in proof['paired_runs'] if r['context_seconds']==context['context_seconds']];assert len(pairs)==100
    assert context['physical_oracle_bit_parity'] and context['valid_feature_frames']<=256
    for pair in pairs:
        c,f=pair['results']['cpu'],pair['results']['fpga'];counts=f['counters']
        assert counts['physical_calls']==32 and counts['oracle_calls']==0 and counts['ioctls']==32 and counts['loads']==0
        assert c['length']==f['length']
        assert c['text']==context['initial_cpu_text'] and f['text']==context['initial_fpga_text']
    c=np.array([r['results']['cpu']['seconds'] for r in pairs]);f=np.array([r['results']['fpga']['seconds'] for r in pairs])
    ci=np.percentile(np.random.default_rng(11102026).choice(c-f,(10000,100),replace=True).mean(axis=1),[2.5,97.5])
    values={'cpu_p50':float(np.median(c)),'fpga_p50':float(np.median(f)),'cpu_p95':float(np.percentile(c,95)),'fpga_p95':float(np.percentile(f,95))}
    for key,value in values.items():assert abs(value-context[key])<1e-12
    np.testing.assert_allclose(ci,context['mean_saving_95ci_seconds'],rtol=0,atol=1e-12)
    same=context['initial_cpu_text']==context['initial_fpga_text'];assert same==context['cpu_transcript_exact']
    rows.append(dict(input_seconds=context['context_seconds'],feature_frames=context['valid_feature_frames'],**values,
                     gain_percent=100*(1-values['fpga_p50']/values['cpu_p50']),cpu_transcript_exact=same,
                     mean_saving_95ci_seconds=ci.tolist(),latency_accepted=bool(same and ci[0]>0 and values['fpga_p50']<values['cpu_p50'] and values['fpga_p95']<values['cpu_p95'])))
restore=ROOT/'reports/fused/shortwide_long_board_restoration.json';assert read(restore)['complete']
summary={'complete':True,'hardware_execution':True,'runs_per_context':100,'contexts':rows,
         'unsupported_inputs':proof['unsupported_inputs'],'maximum_window_seconds':2.55,
         'policy_scope':'Inherited 1-second CPU/FPGA policy, not re-tuned for longer inputs',
         'evidence_sha256':{path.relative_to(ROOT).as_posix():sha(path),restore.relative_to(ROOT).as_posix():sha(restore)},
         'representative_corpus_qualified':False,'capture_tested':False}
(ROOT/'reports/fused/shortwide_long_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
table=['| Input | Frames | CPU p50 / p95 | FPGA p50 / p95 | p50 reduction | CPU text parity |','| --- | --- | --- | --- | --- | --- |']
for r in rows:table.append(f"| {r['input_seconds']:g} s | {r['feature_frames']} | {r['cpu_p50']*1000:.2f} / {r['cpu_p95']*1000:.2f} ms | {r['fpga_p50']*1000:.2f} / {r['fpga_p95']*1000:.2f} ms | {r['gain_percent']:.2f}% | {r['cpu_transcript_exact']} |")
(ROOT/'LONG_INPUT_RESULTS.md').write_text('\n'.join(['# Longer-input physical tests','',*table,'',
    'Each context has 100 fresh randomized paired warm runs on the user recording. Timings include frontend, model, decoding and all warm transfers. Both paths use four CPU threads; CPU spin is 10 us, FPGA spin is disabled, main core is 3 and DMA IRQ core is 3. These are the inherited verified 1-second settings; this test did not re-screen scheduling.', '',
    'Each context passed physical/oracle logits parity and exact CPU output lengths. Text parity is shown per context. Every warm FPGA call executed 32 retained pairs, 32 ioctls and zero weight loads. Accepted bulk firmware, driver, clock and IRQ masks were restored and verified.', '',
    'The current hardware and resident API support at most 256 feature frames / 2.55 s. 3-second, 5-second and full-recording windows were checked for frame counts and reported as unsupported; they were not run as FPGA or fallback benchmarks. Longer whole-window inference requires expanding the retained buffer and re-validating hardware.', '',
    'These are diagnostic single-recording tests. Representative corpus accuracy and live capture remain unqualified. The existing short-window checkpoints were preserved.'
])+'\n')
print(json.dumps(summary))
