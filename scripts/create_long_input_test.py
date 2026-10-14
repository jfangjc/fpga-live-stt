"""Create a separate longer-window benchmark without changing accepted artifacts."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'software/latency/confirm_short_wide_schedule.py').read_text()
def replace(old,new):
    global text
    assert old in text,old
    text=text.replace(old,new)
replace('assert a.runs>=300','assert a.runs>=100')
replace('cfg=policies[seconds];configure',"cfg=policies[1.0];configure")
replace('rng=random.Random(1110202602)','rng=random.Random(1110202612)')
replace('rows=[];summaries=[];startup={};irq_before=snapshot()', 'rows=[];summaries=[];startup={};irq_before=snapshot();limits=[]\n    for seconds in (3.0,5.0,len(audio)/16000):\n        if seconds>len(audio)/16000:continue\n        x,n=frontend(np.ascontiguousarray(audio[:round(seconds*16000)]))\n        limits.append({\'input_seconds\':seconds,\'valid_feature_frames\':int(n[0]),\'physical_execution\':False,\'reason\':\'Exceeds current resident API 2.55-second window and 256-frame hardware limit; no fallback benchmark\'})')
replace('assert .02<=seconds<=len(audio)/16000','assert 1<seconds<=min(2.55,len(audio)/16000)')
replace("            clip=np.ascontiguousarray(audio[:round(seconds*16000)])", "            clip=np.ascontiguousarray(audio[:round(seconds*16000)])\n            probe_x,probe_n=frontend(clip)\n            assert int(probe_n[0])<=256,'Physical frame limit exceeded'")
replace("assert first['text']==emulated['text']==cpu['text'] and first['length']==cpu['length']", "assert first['text']==emulated['text'] and first['length']==cpu['length']\n            transcript_exact=first['text']==cpu['text']\n            expected_text={'cpu':cpu['text'],'fpga':first['text']}\n            startup[str(seconds)]['initial_cpu_result']=cpu")
replace("assert results['cpu']['text']==results['fpga']['text']", "assert all(results[k]['text']==expected_text[k] for k in ('cpu','fpga'))")
replace("'physical_oracle_bit_parity':True,'cpu_spin_duration_us':cpu_spin,", "'physical_oracle_bit_parity':True,'cpu_transcript_exact':transcript_exact,\n                     'valid_feature_frames':int(probe_n[0]),'initial_cpu_text':cpu['text'],'initial_fpga_text':first['text'],\n                     'policy_scope':'Inherited verified 1-second policy; no longer-window scheduling screen',\n                     'cpu_spin_duration_us':cpu_spin,")
replace("'runtime':'shortwide-scheduled'", "'runtime':'shortwide-long-input-test'")
replace("'startup':startup,'policy_sha256'", "'startup':startup,'unsupported_inputs':limits,'physical_window_limit_seconds':2.55,'policy_sha256'")
(ROOT/'software/latency/test_short_wide_long_inputs.py').write_bytes(text.encode())
shell=(ROOT/'scripts/run_short_wide_physical.sh').read_text()
start=shell.index('.venv/bin/python software/ort_fpga_shortwide/smoke.py')
end=shell.index('restore_bulk\n.venv/bin/python scripts/verify_short_wide_restoration.py',start)
shell=shell[:start]+'.venv/bin/python software/latency/test_short_wide_long_inputs.py --contexts 1.5 2 2.5 2.55 --runs 100 --out reports/fused/shortwide_long_inputs.json\n'+shell[end:]
shell=shell.replace('scripts/verify_short_wide_restoration.py','scripts/verify_short_wide_long_restoration.py').replace('Wider depthwise physical validation finished','Longer-input benchmark finished')
(ROOT/'scripts/run_short_wide_long_inputs.sh').write_bytes(shell.encode())
restore=(ROOT/'scripts/verify_short_wide_restoration.py').read_text().replace('shortwide_board_restoration.json','shortwide_long_board_restoration.json')
(ROOT/'scripts/verify_short_wide_long_restoration.py').write_bytes(restore.encode())
print('Created separate longer-window test and restoration harness')
