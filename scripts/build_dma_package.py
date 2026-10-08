"""Build the board ZIP from an explicit whitelist after routed timing passes."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

root = Path(__file__).resolve().parents[1]
dma_ip = root/'voice_dma/voice_dma.gen/sources_1/bd/voice_dma_system/ip/voice_dma_system_tensor_dma_0/synth/voice_dma_system_tensor_dma_0.vhd'
if 'C_SG_INCLUDE_STSCNTRL_STRM => 0,' not in dma_ip.read_text():
    raise RuntimeError('Optional DMA control/status stream must be disabled')
bit = root/'voice_dma/voice_dma.runs/impl_1/voice_dma_top.bit'
binary = bit.with_suffix('.bit.bin')
if bit.stat().st_mtime < dma_ip.stat().st_mtime or binary.stat().st_mtime < bit.stat().st_mtime:
    raise RuntimeError('Bitstream and Bootgen binary must be regenerated after the DMA IP change')
if (root/'reports/dma_timing.rpt').stat().st_mtime < bit.stat().st_mtime:
    raise RuntimeError('Routed reports must be exported for the new bitstream')
timing = (root/'reports/dma_timing.rpt').read_text()
match = re.search(r'WNS\(ns\).*?\n\s*-.*?\n\s*([-\d.]+)\s+([-\d.]+)\s+\d+\s+\d+\s+([-\d.]+)\s+([-\d.]+)', timing, re.S)
if not match or any(float(v) < 0 for v in match.groups()):
    raise RuntimeError('DMA routed setup/hold timing must pass before packaging')
dest = root/'dma-deployment'
files = {}


def copy(source, relative):
    source = root/source
    target = dest/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source,target)
    files[relative] = target


copy('software/voice-dma.dts','voice-dma/voice-dma.dts')
copy('software/voice-dma.dtbo','voice-dma/voice-dma.dtbo')
copy('voice_dma/voice_dma.runs/impl_1/voice_dma_top.bit.bin','voice-dma/voice-dma.bit.bin')
shell = dest/'voice-dma/shell.json'
shell.write_text(json.dumps({'shell_type':'PL_FLAT','num_pl_slots':0,'num_aie_slots':0},indent=4)+'\n')
files['voice-dma/shell.json'] = shell
for name in ('kv260_voice.py','qn_tile.py','tile_smoke.py','record_audio.py'):
    copy('software/'+name,'software/'+name)
copy('deployment/board_smoke.py','software/board_smoke.py')
for name in ('quartznet_cpu.py','quartznet_hybrid.py','requirements-hybrid.txt','README.md','HYBRID_EXPERIMENT.md',
             'model/config.json','model/vocab.txt','model/revision.txt','model/model.onnx','reference/model_config.yaml'):
    copy('software/asr-baseline/'+name,'software/asr-baseline/'+name)
for name in ('qn_tile.c','qn_tile_uapi.h','Makefile','README.md','prebuilt/6.8.0-1015-xilinx/qn_tile.ko'):
    copy('software/tile-driver/'+name,'tile-driver/'+name)
copy('software/DMA_BOARD_COMMANDS.md','README.md')
for name in ('dma_timing.rpt','dma_utilization.rpt','dma_drc.rpt','tile_validation.txt',
             'dma_validation.txt','kernel_6.8.0-1015-xilinx_validation.txt',
             'dma_board_timeout.json','kernel_dma_timeout_review.txt','quartznet_hybrid_host.json',
             'quartznet_original_parity.json','quartznet_board_baseline.json'):
    copy('reports/'+name,'validation/'+name)
manifest = dest/'SHA256SUMS'
manifest.write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+name+'\n'
                          for name,path in sorted(files.items())),encoding='utf-8')
files['SHA256SUMS'] = manifest
archive = root/'voice-dma-prototype.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for name,path in sorted(files.items()):
        z.write(path,'dma-deployment/'+name)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert set(z.namelist()) == {'dma-deployment/'+name for name in files}
    for line in z.read('dma-deployment/SHA256SUMS').decode().splitlines():
        expected,name = line.split('  ',1)
        assert hashlib.sha256(z.read('dma-deployment/'+name)).hexdigest() == expected
result = {'zip':str(archive),'bytes':archive.stat().st_size,'files':len(files),
                  'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                  'integrity':'PASS','firmware_revision':'dma-status-stream-disabled',
                  'hardware_board_validation':'pending'}
(root/'reports/dma_package.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
