"""Create a separate physical-result auditor; never overwrite the verified parent."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'scripts/summarize_short_cache_schedule.py').read_text()
text=text.replace('shortcache_scheduled_', 'shortwide_scheduled_').replace('shortcache_physical_validation','shortwide_physical_validation')
text=text.replace('confirm_short_cache_schedule.py','confirm_short_wide_schedule.py').replace('ort_fpga_shortcache','ort_fpga_shortwide')
text=text.replace('experimental-shortcache','experimental-shortwide').replace('asr-v3-shortcache','asr-v3-shortwide')
text=text.replace('short_cache_scheduled_resident.py','short_wide_resident.py').replace('shortwide_scheduled_board_restoration','shortwide_board_restoration')
text=text.replace("    assert f.size==300 and ci[0]>0 and values['fpga_p50']<values['cpu_p50'] and values['fpga_p95']<values['cpu_p95']", "    assert f.size==300\n    accepted=bool(ci[0]>0 and values['fpga_p50']<values['cpu_p50'] and values['fpga_p95']<values['cpu_p95'])")
text=text.replace("gain_percent=float(100*(1-np.median(f)/np.median(c)))", "latency_accepted=accepted,gain_percent=float(100*(1-np.median(f)/np.median(c)))")
text=text.replace("'whole_model_latency_accepted':True", "'whole_model_latency_accepted':all(r['latency_accepted'] for r in rows)")
text=text.replace("all(r['gain_percent']>=10 for r in rows)", "all(r['latency_accepted'] and r['gain_percent']>=10 for r in rows)")
marker="summary={'complete':True"
assert marker in text
gate="""firmware=ROOT/'reports/fused/shortwide_firmware_evidence.json';evidence=read(firmware)
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
"""
text=text.replace(marker,gate+marker)
text=text.replace('SHORT_CACHE_SCHEDULE_RESULTS.md','SHORT_WIDE_RESULTS.md')
start=text.index("(ROOT/'SHORT_WIDE_RESULTS.md').write_text")
end=text.index('print(json.dumps(summary))',start)
text=text[:start]+"""(ROOT/'SHORT_WIDE_RESULTS.md').write_text('\\n'.join([
    '# Wider-depthwise physical FPGA results','',*table,'',
    'Fresh 300-run randomized paired warm measurements per input include frontend, model, decoding and all warm FPGA transfers. CPU uses the fastest screened valid policy. FPGA graph selection, native binary and driver are unchanged; depthwise hardware widened from 16 to 64 time lanes.', '',
    f"Whole-model latency gate: {summary['whole_model_latency_accepted']}. At least 10% p50 reduction on both inputs: {summary['ten_percent_latency_accepted']}.", '',
    '240 isolated arithmetic checks matched independent NumPy exactly, including frame-boundary cases. The 36 diagnostic prefixes matched physical INT8 oracle logits and CPU transcripts/lengths. Warm calls executed 32 retained pairs (64 convolutions), 32 ioctls and zero weight reloads. The resident API and board restoration checks passed.', '',
    'Timing meets 100 MHz. Representative corpus accuracy and live capture remain unqualified; prefix transcripts remain provisional.'
])+'\\n')
"""+text[end:]
(ROOT/'scripts/summarize_short_wide_results.py').write_bytes(text.encode())
print('Created independent wider hardware result auditor')
