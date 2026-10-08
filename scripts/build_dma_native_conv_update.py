"""Package only ARM userspace native Conv files, preserving working DMA RTL."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import zipfile

root = Path(__file__).resolve().parents[1]
native = root/'software/asr-baseline/native'
library = native/'prebuilt/libqn_depthwise_aarch64.so'
binary = library.read_bytes()
assert binary[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H',binary,18)[0] == 183
assert b'qn_depthwise_f32' in binary
build = json.loads((native/'prebuilt/provenance.json').read_text())
assert build['sha256'] == hashlib.sha256(binary).hexdigest()
assert build['source_sha256'] == hashlib.sha256((native/'qn_depthwise.c').read_bytes()).hexdigest()
assert build['fused_fp_instructions'] == 0 and build['neon_fmul_instructions'] > 0
model = json.loads((root/'reports/native_ctypes_host.json').read_text())
assert model['result'] == 'PASS' and model['model_fixture_checks'] == 462
full = json.loads((root/'reports/native_graph_host.json').read_text())
assert full['execution'] == 'PASS' and full['native_cpu_nodes'] == 77
assert full['pointwise_nodes_preserved'] == 94 and full['native_conv_calls'] == 231
host = json.loads((native/'host/validation.json').read_text())
assert host['result'] == 'PASS'
assert 'PASS' in (native/'host/sanitizer_validation.txt').read_text()
provenance = {
    'architecture':'AArch64 Cortex-A53 Linux userspace',
    'source_sha256':hashlib.sha256((native/'qn_depthwise.c').read_bytes()).hexdigest(),
    'library_sha256':hashlib.sha256(binary).hexdigest(),
    'compiler':'Ubuntu GCC 13.3.0',
    'flags':'-O3 -std=c11 -mcpu=cortex-a53 -fno-fast-math -ffp-contract=off -fPIC -shared -pthread',
    'arm_execution':'pending board smoke and model test',
    'host_validation':'Portable C model fixtures plus full graph through WSL IPC; ASan/UBSan passed',
    'whole_graph_bit_exact':False,
    'accuracy_validated':False,
    'fpga_driver_and_bitstream_changed':False,
    'default_backend':'numpy'
}
stage = root/'dma-native-conv-update'
stage.mkdir(exist_ok=True)
files = {}
for source,name in {
    'software/asr-baseline/quartznet_hybrid.py':'software/asr-baseline/quartznet_hybrid.py',
    'software/asr-baseline/native_depthwise.py':'software/asr-baseline/native_depthwise.py',
    'software/asr-baseline/native_smoke.py':'software/asr-baseline/native_smoke.py',
    'software/asr-baseline/native/qn_depthwise.c':'software/asr-baseline/native/qn_depthwise.c',
    'software/asr-baseline/native/Makefile':'software/asr-baseline/native/Makefile',
    'software/asr-baseline/native/prebuilt/libqn_depthwise_aarch64.so':'software/asr-baseline/native/prebuilt/libqn_depthwise_aarch64.so',
    'software/asr-baseline/native/prebuilt/provenance.json':'validation/arm_build_provenance.json',
    'software/profile_dma.py':'software/profile_dma.py',
    'software/DMA_NATIVE_CONV_COMMANDS.md':'README.md',
    'reports/native_ctypes_host.json':'validation/native_ctypes_host.json',
    'reports/native_graph_host.json':'validation/native_graph_host.json',
    'software/asr-baseline/native/host/validation.json':'validation/native_shapes_host.json',
    'software/asr-baseline/native/host/sanitizer_validation.txt':'validation/native_sanitizers_host.txt',
    'reports/quartznet_cpu_operations_board.json':'validation/quartznet_cpu_operations_board.json',
}.items():
    target = stage/name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(root/source,target)
    files[name] = target
target = stage/'validation/native_build.json'
target.write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf-8')
files['validation/native_build.json'] = target
manifest = stage/'SHA256SUMS'
manifest.write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+name+'\n'
                          for name,path in sorted(files.items())),encoding='utf-8')
files['SHA256SUMS'] = manifest
archive = root/'voice-dma-native-conv-update.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name,path in sorted(files.items()):
        z.write(path,'dma-native-conv-update/'+name)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert set(z.namelist()) == {'dma-native-conv-update/'+name for name in files}
    assert not any('host/' in name or 'build/' in name for name in z.namelist())
    assert [name for name in z.namelist() if name.endswith('.so')] == [
        'dma-native-conv-update/software/asr-baseline/native/prebuilt/libqn_depthwise_aarch64.so']
    for line in z.read('dma-native-conv-update/SHA256SUMS').decode().splitlines():
        expected,name = line.split('  ',1)
        assert hashlib.sha256(z.read('dma-native-conv-update/'+name)).hexdigest() == expected
report = {'archive':archive.name,'bytes':archive.stat().st_size,
          'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
          'integrity':'PASS','board_performance_and_accuracy':'pending'}
(root/'reports/dma_native_conv_package.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
