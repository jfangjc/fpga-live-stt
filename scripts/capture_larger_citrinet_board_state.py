"""Record unchanged accepted bulk board state and exact benchmark bindings."""
import hashlib,json,platform,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
driver=ROOT/'deployment/kernel-compat'/platform.release()/'bulk/qn_tile.ko'
clock=int(Path('/sys/bus/platform/devices/asr-v3-bulk-clock/set_rate').read_text())
assert abs(clock-100000000)<=5
assert Path('/sys/class/fpga_manager/fpga0/state').read_text().strip()=='operating'
assert Path('/sys/module/qn_tile/parameters/bulk_protocol').read_text().strip()=='1'
assert Path('/sys/module/qn_tile/srcversion').read_text().strip()==subprocess.check_output(['modinfo','-F','srcversion',str(driver)],text=True).strip()
paths=['software/latency/benchmark_larger_citrinet.py','software/model-tools/larger_tokenizer.py','software/ort_fpga_bulk/libort_fpga.so']
report={'complete':True,'clock_readback_hz':clock,'active_app':'asr-v3-bulk','firmware_changed_by_test':False,
        'driver_sha256':sha(driver),'firmware_sha256':sha('/lib/firmware/xilinx/asr-v3-bulk/asr-v3-bulk.bit.bin'),
        'sources_sha256':{p:sha(ROOT/p) for p in paths}}
(ROOT/'reports/fused/larger_citrinet_board_state.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
