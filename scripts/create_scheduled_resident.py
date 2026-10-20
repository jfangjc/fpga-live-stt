"""Create a separate resident API for the confirmed asymmetric worker policy."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'software/ort_fpga_shortcache/resident.py').read_text()
def replace(old,new):
    global text
    assert old in text,old
    text=text.replace(old,new)
replace('class ShortCacheResidentTranscriber(', 'class ScheduledShortCacheResidentTranscriber(')
replace("proof.get('runtime')=='shortcache'", "proof.get('runtime')=='shortcache-scheduled'")
replace("        model=ROOT/", "        policy_path=ROOT/'reports/fused/shortcache_schedule_screen.json'\n        if sha(policy_path)!=proof['policy_sha256'] or sha(ROOT/'software/latency/confirm_short_cache_schedule.py')!=proof['source_sha256']:\n            raise ValueError('Scheduling confirmation source/policy mismatch')\n        policy=json.loads(policy_path.read_text())\n        context=proof['contexts'][0]\n        selected=next(r for r in policy['selected'] if r['context_seconds']==context['context_seconds'])\n        for key in ('cpu_spin_duration_us','fpga_spin_duration_us','dma_irq_core'):\n            if context[key]!=selected[key]:raise ValueError('Unconfirmed execution policy')\n        runtime=ROOT/'software/ort_fpga_shortcache'\n        model=ROOT/")
for name in ('validate.py','graph.py','selection.json','libort_fpga.so'):
    replace("Path(__file__).with_name('"+name+"')", "(runtime/'"+name+"')")
replace("spin=proof['contexts'][0]['spin_duration_us']", "spin=context['fpga_spin_duration_us' if backend=='fpga' else 'cpu_spin_duration_us']")
replace("'experiment':'32_resident_pairs'", "'experiment':'32_resident_pairs_scheduled'")
(ROOT/'software/latency/short_cache_scheduled_resident.py').write_bytes(text.encode())
check=(ROOT/'software/ort_fpga_shortcache/check_resident.py').read_text()
check=check.replace('from resident import ShortCacheResidentTranscriber','from short_cache_scheduled_resident import ScheduledShortCacheResidentTranscriber')
check=check.replace('ShortCacheResidentTranscriber(report','ScheduledShortCacheResidentTranscriber(report')
check=check.replace('shortcache_total_', 'shortcache_scheduled_')
check=check.replace('shortcache_resident_validation.json','shortcache_scheduled_resident_validation.json')
check=check.replace("Path(__file__).with_name('resident.py')","Path(__file__).with_name('short_cache_scheduled_resident.py')")
(ROOT/'software/latency/check_short_cache_scheduled_resident.py').write_bytes(check.encode())
restore=(ROOT/'scripts/verify_short_cache_restoration.py').read_text().replace('shortcache_board_restoration.json','shortcache_scheduled_board_restoration.json')
(ROOT/'scripts/verify_short_cache_scheduled_restoration.py').write_bytes(restore.encode())
shell=(ROOT/'scripts/run_short_cache_confirmation.sh').read_text()
start=shell.index('.venv/bin/python software/latency/confirm_short_cache_schedule.py')
end=shell.index('restore_bulk\necho',start)
shell=shell[:start]+'.venv/bin/python software/latency/check_short_cache_scheduled_resident.py\n'+shell[end:]
shell=shell.replace("echo 'Fresh scheduling confirmation finished; accepted bulk restored.'", ".venv/bin/python scripts/verify_short_cache_scheduled_restoration.py\necho 'Scheduled resident API verified; accepted bulk restored.'")
(ROOT/'scripts/run_short_cache_scheduled_resident.sh').write_bytes(shell.encode())
print('Created independent scheduled resident API and checks')
