"""Queue maskfast full-path qualification after existing physical jobs end."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def save(name,text):
    dest=ROOT/name
    if dest.exists():assert dest.read_text()==text,dest
    else:dest.write_text(text,newline='\n')
for kind in ('validate','tune','confirm'):
    suffix={'validate':'physical','tune':'policy','confirm':'latency'}[kind]
    old=f'software/latency/{kind}_branch512_outslice166_more_{suffix}.py'
    text=(ROOT/old).read_text().replace('branch512_outslice166_more','branch512_outslice166_maskfast')
    if kind=='tune':
        text=text.replace('branch512_cpu_pool_policy_clean.json','branch512_maskfast_cpu_policy_clean.json')
        text=text.replace("cpu_policies={", "assert cpu_screen['maskfast_library_sha256']==sha(items['maskfast_library'])\nassert cpu_screen['maskfast_validation_sha256']==sha(items['maskfast_validation'])\ncpu_policies={")
    if kind=='confirm':
        text=text.replace("rng.shuffle(order);results={}","rng.shuffle(order);results={};outputs={}")
        text=text.replace("results[kind],_=timer.call", "results[kind],outputs[kind]=timer.call")
        text=text.replace("            rows.append({'index':iteration,'order':order,'results':results})", "            # Compare outside the measured call; never include validation time in either path.\n            np.testing.assert_array_equal(outputs['cpu'],outputs['fpga'])\n            np.testing.assert_array_equal(outputs['fpga'],actual)\n            rows.append({'index':iteration,'order':order,'results':results,'all_logits_bit_exact':True})")
        text=text.replace("'physical_oracle_bit_exact':True,'all_text_and_lengths_equal':True", "'physical_oracle_bit_exact':True,'all_text_and_lengths_equal':True,'all_warm_logits_bit_exact':True,'warm_logit_checks':a.runs")
    save(old.replace('branch512_outslice166_more','branch512_outslice166_maskfast'),text)
text=(ROOT/'scripts/qualify_branch512_outslice166_more.py').read_text()
text=text.replace('branch512_outslice166_more','branch512_outslice166_maskfast')
text=text.replace("confirmation=ROOT/'reports/fused/branch512_outslice166_scale_latency_confirmation.json'", "confirmation=ROOT/'reports/fused/branch512_outslice166_more_latency_confirmation.json'")
text=text.replace("qualification=ROOT/'build/branch512_outslice166_scale_qualification_driver.log'", "qualification=ROOT/'build/branch512_outslice166_more_qualification_driver.log'")
text=text.replace("deadline=time.monotonic()+6*3600", "deadline=time.monotonic()+8*3600")
index=text.index("download('reports/fused/branch512_more_pool_oracle.json')")
wait='''# Existing NEON job is sequential after more; do not overlap physical tests.
while True:
    neon=ROOT/'reports/fused/branch512_outslice166_neon_latency_confirmation.json'
    log=ROOT/'build/branch512_outslice166_neon_qualification_driver.log'
    if neon.exists():
        try:
            p=json.loads(neon.read_text())
            if p['complete'] and p['hardware_execution']:break
        except (json.JSONDecodeError,PermissionError):pass
    if log.exists() and 'optional vector experiment was not started' in read_log(log):break
    if log.exists() and 'Traceback (most recent call last)' in read_log(log):
        raise RuntimeError('Prior NEON job failed; maskfast physical tests were not started')
    if time.monotonic()>deadline:raise TimeoutError('Prior physical qualification has not finished')
    time.sleep(5)
download('reports/fused/branch512_maskfast_cpu_policy_clean.json')
download('reports/fused/branch512_maskfast_cpu_policy_clean.log')
'''
text=text[:index]+wait+text[index:]
a=text.index("p=physical('test_outslice_stride_pointwise_physical.py'")
b=text.index("p=physical('validate_branch512_outslice166_maskfast_physical.py'",a)
text=text[:a]+"# FPGA arithmetic, protocol and library are unchanged from more; revalidate full model with the new CPU tail.\n"+text[b:]
text=text.replace('FPGA-ASR-output-pipeline-retention-confirmed-2026-10-13','FPGA-ASR-output-pipeline-maskfast-confirmed-2026-10-13')
save('scripts/qualify_branch512_outslice166_maskfast.py',text)
print('Prepared masked-tail physical parity and strongest-CPU 300-pair qualification')
