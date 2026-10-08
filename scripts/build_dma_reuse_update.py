"""Archive user board results and verify a software-only packet reuse update."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

root = Path(__file__).resolve().parents[1]
attachment = Path('C:/Users/jfang/.codex/attachments/27b55d7b-fb13-4b89-90ca-ccf69289498e/Pasted text.txt')
raw = attachment.read_text(encoding='utf-8-sig')
decoder = json.JSONDecoder()
objects = []
position = 0
while True:
    position = raw.find('{',position)
    if position < 0:
        break
    value,consumed = decoder.raw_decode(raw[position:])
    objects.append(value)
    position += consumed
assert len(objects) == 2
board = {'source':'User-supplied KV260 console output', 'run':objects[0],
         'profile':objects[1],'conclusion':'No measured speed improvement over packing+NumPy CPU Conv run'}
(root/'reports/quartznet_cpu_conv_ort_board.json').write_text(json.dumps(board,indent=2)+'\n')
graph = json.loads((root/'reports/quartznet_batch_graph_host.json').read_text())
assert graph['nodes_checked'] == 266 and graph['all_node_outputs_bit_exact']
assert graph['tile_packets'] == 77376 and graph['batch_calls'] == 1209
checks = json.loads((root/'reports/dma_reuse_host.json').read_text())
assert checks['result'] == 'PASS' and checks['independent_int64_cases'] == 25
packing = json.loads((root/'reports/dma_reuse_packing_host.json').read_text())
assert packing['result'] == 'PASS'
assert all(b['wire_packets_identical'] for b in packing['packing_benchmarks'])
stage = root/'dma-reuse-update'
stage.mkdir(exist_ok=True)
files = {}
for source,name in {
    'software/qn_tile.py':'software/qn_tile.py',
    'software/DMA_REUSE_COMMANDS.md':'README.md',
    'reports/dma_reuse_host.json':'validation/dma_reuse_host.json',
    'reports/dma_reuse_packing_host.json':'validation/dma_reuse_packing_host.json',
    'reports/quartznet_batch_graph_host.json':'validation/quartznet_batch_graph_host.json',
    'reports/quartznet_cpu_conv_ort_board.json':'validation/quartznet_cpu_conv_ort_board.json',
}.items():
    target = stage/name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(root/source,target)
    files[name] = target
manifest = stage/'SHA256SUMS'
manifest.write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+name+'\n'
                          for name,path in sorted(files.items())),encoding='utf-8')
files['SHA256SUMS'] = manifest
archive = root/'voice-dma-reuse-update.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name,path in sorted(files.items()):
        z.write(path,'dma-reuse-update/'+name)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert set(z.namelist()) == {'dma-reuse-update/'+name for name in files}
    for line in z.read('dma-reuse-update/SHA256SUMS').decode().splitlines():
        expected,name = line.split('  ',1)
        assert hashlib.sha256(z.read('dma-reuse-update/'+name)).hexdigest() == expected
report = {'archive':archive.name,'bytes':archive.stat().st_size,
          'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'integrity':'PASS',
          'board_speed_for_update':'pending'}
(root/'reports/dma_reuse_package.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
