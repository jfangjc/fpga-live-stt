"""Verify and package an optional CPU Conv software update."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

root = Path(__file__).resolve().parents[1]
validation = json.loads((root/'reports/quartznet_cpu_conv_ort_host.json').read_text())
assert validation['result'] == 'PASS' and validation['isolated_cpu_conv_checks'] == 231
assert validation['cpu_conv_sessions'] == 77 and validation['pointwise_nodes_preserved'] == 94
stage = root/'dma-cpu-conv-update'
stage.mkdir(exist_ok=True)
files = {}
for source,name in {
    'software/asr-baseline/quartznet_hybrid.py':'software/asr-baseline/quartznet_hybrid.py',
    'software/profile_dma.py':'software/profile_dma.py',
    'software/DMA_CPU_CONV_COMMANDS.md':'README.md',
    'reports/quartznet_cpu_conv_ort_host.json':'validation/quartznet_cpu_conv_ort_host.json',
    'reports/quartznet_packing_board.json':'validation/quartznet_packing_board.json',
}.items():
    target = stage/name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(root/source,target)
    files[name] = target
manifest = stage/'SHA256SUMS'
manifest.write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+name+'\n'
                          for name,path in sorted(files.items())),encoding='utf-8')
files['SHA256SUMS'] = manifest
archive = root/'voice-dma-cpu-conv-update.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name,path in sorted(files.items()):
        z.write(path,'dma-cpu-conv-update/'+name)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert set(z.namelist()) == {'dma-cpu-conv-update/'+name for name in files}
    for line in z.read('dma-cpu-conv-update/SHA256SUMS').decode().splitlines():
        expected,name = line.split('  ',1)
        assert hashlib.sha256(z.read('dma-cpu-conv-update/'+name)).hexdigest() == expected
result = {'archive':archive.name,'bytes':archive.stat().st_size,
          'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
          'integrity':'PASS','board_speed_and_accuracy_for_update':'pending'}
(root/'reports/dma_cpu_conv_package.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
