"""Package and verify a software-only update; preserve loaded firmware/driver."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

root = Path(__file__).resolve().parents[1]
attachment = Path('C:/Users/jfang/.codex/attachments/bc821220-e07d-4999-b50c-2b94f42a8d9c/Pasted text.txt')
raw = attachment.read_text(encoding='utf-8-sig')
decoder = json.JSONDecoder()
objects = []
position = 0
while True:
    position = raw.find('{',position)
    if position < 0:
        break
    value, consumed = decoder.raw_decode(raw[position:])
    objects.append(value)
    position += consumed
assert len(objects) == 3
profile = {'source':'User-supplied board console output',
           'batch64_summary':objects[0], 'batch128_run':objects[1],
           'batch128_profile':objects[2]}
(root/'reports/quartznet_profile128_board.json').write_text(json.dumps(profile,indent=2)+'\n')
host = json.loads((root/'reports/quartznet_batch_graph_host.json').read_text())
assert host['all_node_outputs_bit_exact'] and host['nodes_checked'] == 266
assert json.loads((root/'reports/dma_packing_host.json').read_text())['result'] == 'PASS'
assert json.loads((root/'reports/quartznet_packing_smoke_host.json').read_text())['all_exact']
stage = root/'dma-packing-update'
stage.mkdir(exist_ok=True)
files = {}
sources = {
    'software/qn_tile.py':'software/qn_tile.py',
    'software/profile_dma.py':'software/profile_dma.py',
    'software/DMA_PACKING_COMMANDS.md':'README.md',
    'reports/dma_packing_host.json':'validation/dma_packing_host.json',
    'reports/quartznet_batch_graph_host.json':'validation/quartznet_batch_graph_host.json',
    'reports/quartznet_packing_smoke_host.json':'validation/quartznet_packing_smoke_host.json',
    'reports/quartznet_profile128_board.json':'validation/quartznet_profile128_board.json',
}
for source,name in sources.items():
    target = stage/name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(root/source,target)
    files[name] = target
manifest = stage/'SHA256SUMS'
manifest.write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+name+'\n'
                          for name,path in sorted(files.items())),encoding='utf-8')
files['SHA256SUMS'] = manifest
archive = root/'voice-dma-packing-update.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name,path in sorted(files.items()):
        z.write(path,'dma-packing-update/'+name)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert set(z.namelist()) == {'dma-packing-update/'+name for name in files}
    for line in z.read('dma-packing-update/SHA256SUMS').decode().splitlines():
        expected,name = line.split('  ',1)
        assert hashlib.sha256(z.read('dma-packing-update/'+name)).hexdigest() == expected
result = {'archive':archive.name,'bytes':archive.stat().st_size,
          'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
          'integrity':'PASS','board_performance_for_update':'pending'}
(root/'reports/dma_packing_package.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
