"""Package corrected DMA firmware without re-copying the model or Python venv."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

root = Path(__file__).resolve().parents[1]
base = root/'dma-deployment'
stage = root/'dma-status-fix'
names = ['voice-dma/voice-dma.bit.bin','voice-dma/voice-dma.dtbo','voice-dma/shell.json']
files = {}
for name in names:
    src = base/name
    target = stage/name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, target)
    files[name] = target
target = stage/'README.md'
shutil.copyfile(root/'software/DMA_STATUS_FIX_COMMANDS.md', target)
files['README.md'] = target
manifest = stage/'SHA256SUMS'
manifest.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+name+'\n'
                          for name,p in sorted(files.items())), encoding='utf-8')
files['SHA256SUMS'] = manifest
archive = root/'voice-dma-status-fix.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for name,path in sorted(files.items()):
        z.write(path,'dma-status-fix/'+name)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert set(z.namelist()) == {'dma-status-fix/'+name for name in files}
    for line in z.read('dma-status-fix/SHA256SUMS').decode().splitlines():
        expected,name = line.split('  ',1)
        assert hashlib.sha256(z.read('dma-status-fix/'+name)).hexdigest() == expected
result = {'archive':archive.name,'bytes':archive.stat().st_size,
                  'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                  'integrity':'PASS','corrected_board_result':'pending'}
(root/'reports/dma_status_patch.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
