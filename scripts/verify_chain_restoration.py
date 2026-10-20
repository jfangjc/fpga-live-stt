"""Verify kernel-compatible bulk rollback and restore its original IRQ masks."""
import argparse,hashlib,json,platform,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'software/latency'))
from dma_irq import snapshot
ap=argparse.ArgumentParser();ap.add_argument('--capture',action='store_true');ap.add_argument('--before',type=Path,required=True)
ap.add_argument('--out',type=Path);a=ap.parse_args()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
firmware=Path('/lib/firmware/xilinx/asr-v3-bulk/asr-v3-bulk.bit.bin')
driver=ROOT/'deployment/kernel-compat'/platform.release()/'bulk/qn_tile.ko'
assert sha(firmware)=='b8381da2d15c7b60dc1bb97aa27534897c7977e20ab03e8894bd91e5c345c32e'
module=Path('/sys/module/qn_tile/srcversion').read_text().strip()
assert module==subprocess.check_output(['modinfo','-F','srcversion',str(driver)],text=True).strip()
assert subprocess.check_output(['modinfo','-F','vermagic',str(driver)],text=True).split()[0]==platform.release()
assert Path('/sys/module/qn_tile/parameters/bulk_protocol').read_text().strip()=='1'
assert Path('/sys/class/fpga_manager/fpga0/state').read_text().strip()=='operating'
clock=int(Path('/sys/bus/platform/devices/asr-v3-bulk-clock/set_rate').read_text());assert abs(clock-100000000)<=1
assert Path('/dev/qn-tile').is_char_device()
irq=snapshot()
if not a.capture:
    before=json.loads(a.before.read_text());assert before['driver_sha256']==sha(driver)
    old=sorted(before['irq'],key=int);new=sorted(irq,key=int);assert len(old)==len(new)==2
    for previous,current in zip(old,new):(Path('/proc/irq')/current/'smp_affinity_list').write_text(before['irq'][previous]['requested'])
    irq=snapshot()
    assert [irq[i]['requested'] for i in new]==[before['irq'][i]['requested'] for i in old]
report={'complete':True,'accepted_application':'asr-v3-bulk','kernel':platform.release(),'clock_hz':100000000,'clock_readback_hz':clock,
        'firmware_sha256':sha(firmware),'driver_sha256':sha(driver),'loaded_module_srcversion':module,
        'irq':irq,'source_sha256':sha(Path(__file__)),'capture':a.capture}
out=a.before if a.capture else a.out;assert out is not None
out.write_text(json.dumps(report,indent=2)+'\n');print('PASS: compatible bulk image, loaded module, clock, device and IRQ masks')
