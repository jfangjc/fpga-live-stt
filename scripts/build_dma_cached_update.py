"""Whitelist the cached-layer board update after fresh simulation/routing gates.

No model download and no board programming are performed by this packager.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def require(condition,message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    project = ROOT/'voice_cached_dma'
    bit = project/'voice_cached_dma.runs/impl_1/voice_cached_dma_top.bit'
    binary = bit.with_suffix('.bit.bin')
    ip_files = [p for p in (project/'voice_cached_dma.gen').rglob('*tensor_dma_0.vhd') if p.parent.name=='synth']
    require(len(ip_files)==1,'Expected exactly one generated tensor DMA synthesis wrapper')
    dma_ip = ip_files[0]
    require('C_SG_INCLUDE_STSCNTRL_STRM => 0,' in dma_ip.read_text(),
            'DMA optional control/status stream must be disabled')
    sources = [ROOT/'rtl/qn_cached_axis.v',ROOT/'rtl/qn_tile_axis.v',ROOT/'rtl/qn_mac.v',
               ROOT/'rtl/voice_dma_top.v',ROOT/'rtl/voice_axi.v',ROOT/'rtl/sph0645_rx.v',dma_ip]
    require(bit.stat().st_mtime >= max(p.stat().st_mtime for p in sources),
            'Bitstream must be regenerated after every RTL/DMA source change')
    require(binary.stat().st_mtime >= bit.stat().st_mtime,'Bootgen binary is stale')
    require(binary.stat().st_size>100000,'Bootgen binary is unexpectedly small')
    simulation = ROOT/'reports/cached_sim.log'
    require('PASS: 69 cached arithmetic/protocol/reset cases' in simulation.read_text(),
            'All 69 cached RTL cases must pass')
    require(simulation.stat().st_mtime >= max((ROOT/'rtl/qn_cached_axis.v').stat().st_mtime,
                                            (ROOT/'sim/tb_qn_cached_axis.sv').stat().st_mtime),
            'RTL simulation must be rerun after source/testbench changes')
    graph = json.loads((ROOT/'reports/cached_graph_parity.json').read_text())
    require(graph['all_nodes_exact'] and graph['nodes']==266 and graph['pointwise_nodes']==94,
            'Pinned graph cached emulation parity must pass all nodes')
    require((ROOT/'reports/cached_graph_parity.json').stat().st_mtime >=
            max((ROOT/name).stat().st_mtime for name in ('software/qn_cached.py',
                'software/cached_smoke.py','software/asr-baseline/quartznet_hybrid.py')),
            'Cached graph parity must be rerun after numerical/client changes')
    smoke = json.loads((ROOT/'reports/cached_software_smoke.json').read_text())
    require(smoke['all_exact'],'Cached software arithmetic smoke must pass')
    timing_file = ROOT/'reports/cached_dma_timing.rpt'
    require(timing_file.stat().st_mtime >= bit.stat().st_mtime,'Routed timing report is stale')
    timing = timing_file.read_text()
    match = re.search(r'WNS\(ns\).*?\n\s*-.*?\n\s*([-\d.]+)\s+([-\d.]+)\s+\d+\s+\d+\s+([-\d.]+)\s+([-\d.]+)',timing,re.S)
    require(match is not None and all(float(v)>=0 for v in match.groups()),
            'Routed setup/hold slack and total slack must pass')
    dts = ROOT/'software/voice-cached.dts'
    dtbo = dts.with_suffix('.dtbo')
    require(dtbo.stat().st_mtime >= dts.stat().st_mtime,'Device-tree binary is stale')
    require(dtbo.read_bytes()[:4]==b'\xd0\x0d\xfe\xed','Invalid DTBO magic')
    module = ROOT/'software/tile-driver/prebuilt/6.8.0-1015-xilinx/qn_tile_cached.ko'
    ko = module.read_bytes()
    require(ko[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',ko,18)[0]==183,
            'Cached driver must be AArch64 ELF64')
    build = module.with_name('qn_tile_cached_validation.txt').read_text()
    require(sha(module) in build and sha(ROOT/'software/tile-driver/qn_tile.c') in build and
            sha(ROOT/'software/tile-driver/qn_layer_protocol.h') in build,
            'Driver build provenance must match module and sources')
    require(b'6.8.0-1015-xilinx SMP preempt mod_unload modversions aarch64' in ko,
            'Driver kernel vermagic mismatch')
    library = ROOT/'software/asr-baseline/native/prebuilt/libqn_depthwise_aarch64.so'
    native = json.loads(library.with_name('provenance.json').read_text())
    require(native['sha256']==sha(library),'Native library provenance mismatch')

    stage = ROOT/'dma-cached-update'
    files = {}
    def copy(source,name):
        target = stage/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/source,target)
        files[name] = target

    for name in ('qn_cached.py','qn_tile.py','cached_smoke.py','test_cached.py','tile_smoke.py',
                 'profile_dma.py','CACHED_LAYER_PROTOCOL.md'):
        copy('software/'+name,'software/'+name)
    for name in ('quartznet_cpu.py','quartznet_hybrid.py','native_depthwise.py','native_smoke.py',
                 'requirements-hybrid.txt','native/qn_depthwise.c','native/Makefile',
                 'native/prebuilt/libqn_depthwise_aarch64.so','native/prebuilt/provenance.json'):
        copy('software/asr-baseline/'+name,'software/asr-baseline/'+name)
    for name in ('qn_tile.c','qn_tile_uapi.h','qn_layer_protocol.h','test_layer_protocol.c','Makefile',
                 'CACHED_LAYER.md','CACHED_LAYER_REVIEW.md','prebuilt/6.8.0-1015-xilinx/qn_tile_cached.ko',
                 'prebuilt/6.8.0-1015-xilinx/qn_tile_cached_validation.txt',
                 'prebuilt/6.8.0-1015-xilinx/qn_tile_batch.ko'):
        copy('software/tile-driver/'+name,'tile-driver/'+name)
    copy('software/DMA_CACHED_COMMANDS.md','README.md')
    copy('software/voice-cached.dts','voice-cached/voice-cached.dts')
    copy('software/voice-cached.dtbo','voice-cached/voice-cached.dtbo')
    copy(str(binary.relative_to(ROOT)),'voice-cached/voice-cached.bit.bin')
    shell = stage/'voice-cached/shell.json'
    shell.write_text(json.dumps({'shell_type':'PL_FLAT','num_pl_slots':0,'num_aie_slots':0},indent=4)+'\n')
    files['voice-cached/shell.json'] = shell
    for name in ('cached_graph_parity.json','cached_software_smoke.json','cached_sim.log',
                 'cached_dma_timing.rpt','cached_dma_utilization.rpt','cached_dma_drc.rpt',
                 'cached_architecture_estimate.json','cached_hardware_validation.json'):
        copy('reports/'+name,'validation/'+name)
    for source in ('rtl/qn_cached_axis.v','sim/tb_qn_cached_axis.sv'):
        copy(source,'source/'+source)
    provenance = {'bitstream_sha256':sha(bit),'firmware_sha256':sha(binary),'driver_sha256':sha(module),
                  'kernel':'6.8.0-1015-xilinx','clock_hz':100000000,
                  'rtl_simulation_cases':69,'cached_graph_nodes_exact':266,
                  'dma_status_stream_disabled':True,'board_execution':'pending',
                  'performance_validated':False,'accuracy_validated':False}
    path = stage/'validation/cached_build.json'
    path.write_text(json.dumps(provenance,indent=2)+'\n')
    files['validation/cached_build.json'] = path
    manifest = stage/'SHA256SUMS'
    manifest.write_text(''.join(sha(path)+'  '+name+'\n' for name,path in sorted(files.items())),encoding='utf-8')
    files['SHA256SUMS'] = manifest
    archive = ROOT/'voice-dma-cached-update.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,path in sorted(files.items()):
            z.write(path,'dma-cached-update/'+name)
    with zipfile.ZipFile(archive) as z:
        require(z.testzip() is None,'ZIP CRC failure')
        require(set(z.namelist())=={'dma-cached-update/'+name for name in files},'ZIP whitelist mismatch')
        for line in z.read('dma-cached-update/SHA256SUMS').decode().splitlines():
            digest,name = line.split('  ',1)
            require(hashlib.sha256(z.read('dma-cached-update/'+name)).hexdigest()==digest,'ZIP manifest mismatch')
    result = {'archive':archive.name,'bytes':archive.stat().st_size,'sha256':sha(archive),
              'files':len(files),'integrity':'PASS','board_execution':'pending'}
    (ROOT/'reports/dma_cached_package.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
