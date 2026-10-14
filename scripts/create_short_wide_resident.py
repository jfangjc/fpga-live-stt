"""Generate the separately gated resident API for wider-depthwise physical results."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'software/latency/short_cache_scheduled_resident.py').read_text()
text=text.replace('ScheduledShortCacheResidentTranscriber','ShortWideResidentTranscriber')
text=text.replace("'shortcache-scheduled'","'shortwide-scheduled'")
text=text.replace('confirm_short_cache_schedule.py','confirm_short_wide_schedule.py')
text=text.replace('ort_fpga_shortcache','ort_fpga_shortwide').replace('shortcache_physical_validation','shortwide_physical_validation')
text=text.replace('asr-v3-shortcache','asr-v3-shortwide').replace('experimental-shortcache','experimental-shortwide')
(ROOT/'software/latency/short_wide_resident.py').write_bytes(text.encode())
check=(ROOT/'software/latency/check_short_cache_scheduled_resident.py').read_text()
check=check.replace('from short_cache_scheduled_resident import ScheduledShortCacheResidentTranscriber','from short_wide_resident import ShortWideResidentTranscriber')
check=check.replace('ScheduledShortCacheResidentTranscriber','ShortWideResidentTranscriber')
check=check.replace('shortcache_scheduled_','shortwide_scheduled_').replace('short_cache_scheduled_resident.py','short_wide_resident.py')
(ROOT/'software/latency/check_short_wide_resident.py').write_bytes(check.encode())
restore=(ROOT/'scripts/verify_short_cache_scheduled_restoration.py').read_text().replace('shortcache_scheduled_board_restoration.json','shortwide_board_restoration.json')
(ROOT/'scripts/verify_short_wide_restoration.py').write_bytes(restore.encode())
print('Created separately bound wider-depthwise resident API')
