"""Preserve native CPU board measurements without asserting corpus accuracy."""
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
raw = Path('C:/Users/jfang/.codex/attachments/b99903a5-c330-4a7a-9bf1-0224fd77013c/Pasted text.txt').read_text(encoding='utf-8-sig')
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
assert len(objects) == 4
runs = {}
for run,profile in zip(objects[::2],objects[1::2]):
    assert run['hardware_execution'] and run['native_cpu_conv_calls'] == 77
    assert run['native_cpu_conv_nodes'] == 77 and run['tile_packets'] == 77376
    assert run['ioctl_calls'] == 605
    assert run['native_library_sha256'] == 'f9ddb180e7e3e06d0fee7bebfa59a82fc27fb8eb319e367bd111622a03f156a0'
    runs[str(run['cpu_conv_threads'])] = {'run':run,'profile':profile}
assert set(runs) == {'1','4'}
previous = json.loads((root/'reports/quartznet_reuse_board.json').read_text())
fast = runs['4']['run']
profile = runs['4']['profile']
result = {
    'source':'User-supplied KV260 board console output','runs_by_cpu_threads':runs,
    'same_transcript_on_this_clip':all(r['run']['transcript'] == previous['transcript'] for r in runs.values()),
    'reduction_vs_numpy_percent':100*(1-fast['total_seconds']/previous['total_seconds']),
    'pointwise_outside_ioctl_seconds':profile['int8_pointwise_seconds']-profile['kernel_ioctl_seconds'],
    'ratio_to_corrected_cpu_baseline':fast['total_seconds']/1.9581415380016551,
    'accuracy_validated':False,
    'native_arithmetic_smoke_output':'Not included in attachment; full-model native CPU execution reported',
    'note':'Single-run timings exclude setup/file I/O; one matching transcript does not establish word error rate.'}
(root/'reports/quartznet_native_conv_board.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k != 'runs_by_cpu_threads'},indent=2))
