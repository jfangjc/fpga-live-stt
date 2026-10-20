"""Record the accepted board state after the short-cache physical experiment."""
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'software/latency'))
from dma_irq import snapshot

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

firmware=Path('/lib/firmware/xilinx/asr-v3-bulk/asr-v3-bulk.bit.bin')
driver=ROOT/'deployment/experimental-bulk/qn_tile.ko'
assert sha(firmware)=='b8381da2d15c7b60dc1bb97aa27534897c7977e20ab03e8894bd91e5c345c32e'
assert sha(driver)=='2fbe494b5bf4fea682b72d6e94c6321f2985c3616415fe2a1626809fd2f1f42f'
module_version=Path('/sys/module/qn_tile/srcversion').read_text().strip()
assert module_version==subprocess.check_output(['/usr/sbin/modinfo','-F','srcversion',str(driver)],text=True).strip()
state=Path('/sys/class/fpga_manager/fpga0/state').read_text().strip()
clock=int(Path('/sys/bus/platform/devices/asr-v3-bulk-clock/set_rate').read_text())
assert state=='operating' and 99000000<=clock<=101000000
irq=snapshot()
previous=json.loads((ROOT/'reports/fused/shortcache_irq_restoration.json').read_text())
assert sorted(v['requested'] for v in irq.values())==sorted(v['requested'] for v in previous['before'].values())
report={'complete':True,'accepted_application':'asr-v3-bulk','fpga_state':state,
        'clock_hz':clock,'firmware_sha256':sha(firmware),'driver_sha256':sha(driver),
        'loaded_module_srcversion':module_version,'irq':irq,'source_sha256':sha(Path(__file__))}
(ROOT/'reports/fused/shortwide_long_board_restoration.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS: accepted firmware, loaded driver, clock and DMA IRQ masks restored')
