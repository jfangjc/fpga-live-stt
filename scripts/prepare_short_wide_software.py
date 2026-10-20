"""Create a separate ABI-compatible wider-depthwise experiment without changing its parent."""
import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
parent=json.loads((ROOT/'reports/fused/shortcache_physical_validation.json').read_text())
for name,key in [('software/ort_fpga_shortcache/libort_fpga.so','library_sha256'),('deployment/experimental-shortcache/qn_tile.ko','driver_sha256'),('deployment/asr-v3-shortcache/asr-v3-shortcache.bit.bin','firmware_sha256')]:assert sha(ROOT/name)==parent[key]
runtime=ROOT/'software/ort_fpga_shortwide';driver=ROOT/'deployment/experimental-shortwide';app=ROOT/'deployment/asr-v3-shortwide'
assert not runtime.exists() and not driver.exists() and not app.exists()
shutil.copytree(ROOT/'software/ort_fpga_shortcache',runtime,ignore=shutil.ignore_patterns('__pycache__'))
shutil.copytree(ROOT/'deployment/experimental-shortcache',driver)
app.mkdir()
for path in runtime.glob('*.py'):
    if path.name=='graph.py':continue
    text=path.read_text().replace('asr-v3-shortcache','asr-v3-shortwide').replace('experimental-shortcache','experimental-shortwide').replace('ort_fpga_shortcache','ort_fpga_shortwide').replace('shortcache_', 'shortwide_')
    path.write_bytes(text.encode())
smoke=runtime/'smoke.py';text=smoke.read_text()
old='(256,256,256,255,37,129,7)]'
assert old in text
text=text.replace(old,'(256,256,256,255,37,129,7),(256,256,65,64,220,37,129),\n                                      (256,256,129,127,128,127,128),(256,256,255,253,37,129,7)]')
smoke.write_bytes(text.encode())
for name in ('activate.sh','asr-v3-shortcache.dts','shell.json'):
    text=(ROOT/'deployment/asr-v3-shortcache'/name).read_text().replace('asr-v3-shortcache','asr-v3-shortwide').replace('experimental-shortcache','experimental-shortwide').replace('shortcache_firmware','shortwide_firmware')
    (app/name.replace('shortcache','shortwide')).write_bytes(text.encode())
install=(ROOT/'scripts/install_short_cache_firmware.sh').read_text().replace('asr-v3-shortcache','asr-v3-shortwide').replace('experimental-shortcache','experimental-shortwide').replace('ort_fpga_shortcache','ort_fpga_shortwide').replace('shortcache_firmware','shortwide_firmware')
(ROOT/'scripts/install_short_wide_firmware.sh').write_bytes(install.encode())
confirmation=(ROOT/'software/latency/confirm_short_cache_schedule.py').read_text()
confirmation=confirmation.replace("runtime=ROOT/'software/ort_fpga_shortcache'","runtime=ROOT/'software/ort_fpga_shortwide'").replace('asr-v3-shortcache','asr-v3-shortwide').replace('experimental-shortcache','experimental-shortwide').replace('shortcache_physical_validation','shortwide_physical_validation').replace("'runtime':'shortcache-scheduled'","'runtime':'shortwide-scheduled'")
# The preselected CPU/FPGA policy and graph/library SHA remain unchanged and are re-confirmed with the new firmware.
(ROOT/'software/latency/confirm_short_wide_schedule.py').write_bytes(confirmation.encode())
paths=[ROOT/'rtl/experimental'/n for n in ('qn_short_wide_axis.sv','fused_depthwise_channel_wide.sv','qn_short_cache_core.v','fused_affine_quant.v')]
paths+=[ROOT/'scripts'/n for n in ('short_wide_sim.tcl','short_wide_synth.tcl','build_short_wide_sources.py',Path(__file__).name)]
paths+=[ROOT/'sim/tb_qn_short_cache_axis.sv',runtime/'libort_fpga.so',runtime/'graph.py',runtime/'selection.json',driver/'qn_tile.ko']
(ROOT/'reports/fused/shortwide_source_freeze.json').write_text(json.dumps({'complete':True,'parent_physical_validation_sha256':sha(ROOT/'reports/fused/shortcache_physical_validation.json'),
    'sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths},'native_library_reused':True,'driver_reused':True,'graph_selection_reused':True,'hardware_execution':False},indent=2)+'\n')
print('Prepared separate shortwide software and deployment; ABI binaries unchanged')
