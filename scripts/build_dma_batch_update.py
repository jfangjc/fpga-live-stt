"""Build an explicit software-only batch update and verify its archive."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import zipfile

root = Path(__file__).resolve().parents[1]
prebuilt = root/'software/tile-driver/prebuilt/6.8.0-1015-xilinx'
module = (prebuilt/'qn_tile_batch.ko').read_bytes()
assert module == (root/'software/tile-driver/qn_tile.ko').read_bytes()
assert module[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H',module,18)[0] == 183
assert b'vermagic=6.8.0-1015-xilinx SMP preempt mod_unload modversions aarch64' in module
assert hashlib.sha256((prebuilt/'qn_tile.ko').read_bytes()).hexdigest() == 'cec1a51cc2d34a79b612ce6f99fe5b94e02d2042a4d700b5c2290475a64eaa06'
host = json.loads((root/'reports/quartznet_batch_graph_host.json').read_text())
assert host['all_node_outputs_bit_exact'] and host['nodes_checked'] == 266
assert host['batch_calls'] == 1209 and host['tile_packets'] == 77376
stage = root/'dma-batch-update'
stage.mkdir(exist_ok=True)
files = {}
def copy(source, relative):
    target = stage/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root/source,target)
    files[relative] = target
for name in ('qn_tile.py','batch_smoke.py','asr-baseline/quartznet_hybrid.py'):
    copy('software/'+name,'software/'+name)
for name in ('qn_tile.c','qn_tile_uapi.h','Makefile','prebuilt/6.8.0-1015-xilinx/qn_tile_batch.ko'):
    copy('software/tile-driver/'+name,'tile-driver/'+name)
copy('software/DMA_BATCH_COMMANDS.md','README.md')
for name in ('quartznet_batch_graph_host.json','quartznet_batch_host.json',
             'quartznet_hybrid_board.json','kernel_6.8.0-1015-xilinx_batch_build.txt'):
    copy('reports/'+name,'validation/'+name)
provenance = {
    'kernel':'6.8.0-1015-xilinx', 'architecture':'ARM64', 'build':'exact Ubuntu headers, W=1',
    'module_sha256':hashlib.sha256(module).hexdigest(),
    'source_sha256':hashlib.sha256((root/'software/tile-driver/qn_tile.c').read_bytes()).hexdigest(),
    'uapi_sha256':hashlib.sha256((root/'software/tile-driver/qn_tile_uapi.h').read_bytes()).hexdigest(),
    'legacy_module_preserved':True, 'batch_ioctl':'0x40185102; pointers/packet_bytes/count, 24 bytes',
    'max_batch':128, 'board_batch_validation':'pending',
    'build_notices':'upstream kernel-doc Perl warning; BTF skipped without vmlinux',
    'dma_provider_source_review':'upstream Linuxv6.8; exact Ubuntu provider source inaccessible',
    'callback_helper':'https://raw.githubusercontent.com/torvalds/linux/v6.8/drivers/dma/dmaengine.h'
}
target = stage/'validation/batch_module.json'
target.write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf-8')
files['validation/batch_module.json'] = target
manifest = stage/'SHA256SUMS'
manifest.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+name+'\n'
                          for name,p in sorted(files.items())),encoding='utf-8')
files['SHA256SUMS'] = manifest
archive = root/'voice-dma-batch-update.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for name,path in sorted(files.items()):
        z.write(path,'dma-batch-update/'+name)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert set(z.namelist()) == {'dma-batch-update/'+name for name in files}
    for line in z.read('dma-batch-update/SHA256SUMS').decode().splitlines():
        expected,name = line.split('  ',1)
        assert hashlib.sha256(z.read('dma-batch-update/'+name)).hexdigest() == expected
result = {'archive':archive.name,'bytes':archive.stat().st_size,
          'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
          'integrity':'PASS','board_batch_validation':'pending'}
(root/'reports/dma_batch_package.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
