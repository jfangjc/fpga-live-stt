"""Package the separately routed microphone image; never install or overwrite it.

Prepare after project_streaming.tcl succeeds, compile the staged DTS with dtc,
then finalize to write the hash manifest required by run_moonshine_board.py.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP = 'asr-v3-mic-select'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(out, bootgen):
    build = ROOT/'build/fpga-streaming'
    report = ROOT/'reports/local/streaming-hardware/timing.rpt'
    log = ROOT/'build/streaming-vivado.log'
    if not log.exists() or 'PASS: streaming project build completed' not in log.read_text(errors='replace'):
        raise RuntimeError('Streaming FPGA build has not passed its timing/DRC gates')
    text = report.read_text()
    tail = text[text.index('WNS(ns)'):]
    numeric = next(line.split() for line in tail.splitlines()[1:15] if re.match(r'^\s*-?\d+\.\d+\s', line))
    setup, hold = float(numeric[0]), float(numeric[4])
    if setup < .001 or hold < 0:
        raise RuntimeError('Streaming image misses routed timing')
    xsa = build/'moonshine_stream.xsa'
    tile = build/'moonshine_stream.gen/sources_1/bd/asr_v2_system/ip/asr_v2_system_tile_0/synth/asr_v2_system_tile_0.v'
    if not all(re.search(r'\.MAX_'+name+r'\s*\(1024\)', tile.read_text()) for name in ('K', 'M')):
        raise RuntimeError('Streaming image must preserve the 1024x1024 bulk tile limits')
    out.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(xsa) as archive:
        names = [n for n in archive.namelist() if n.endswith('.bit')]
        if len(names) != 1:
            raise RuntimeError('Expected one bitstream in the routed XSA')
        (out/(APP+'.bit')).write_bytes(archive.read(names[0]))
    (out/'boot.bif').write_text('all:\n{\n  [destination_device = pl] '+APP+'.bit\n}\n')
    subprocess.run([str(Path(bootgen).resolve()), '-arch', 'zynqmp', '-image', 'boot.bif',
                    '-process_bitstream', 'bin'], cwd=out, check=True)
    generated = out/(APP+'.bit.bin')
    if not generated.exists():
        raise RuntimeError('Bootgen did not produce the expected bit.bin')
    source = ROOT/'firmware/asr-v3-bulk'
    (out/(APP+'.dts')).write_text((source/'asr-v3-bulk.dts').read_text().replace('asr-v3-bulk', APP))
    shutil.copy2(source/'shell.json', out/'shell.json')
    files = ['rtl/experimental/'+name for name in ('voice_axi_streaming.v', 'sph0645_stream_rx.v',
              'qn_bulk_axis.v', 'fused_affine_quant.v', 'moonshine_stream_top.v')]
    files += ['hardware/mic_cdc.xdc', 'scripts/project_streaming.tcl']
    metadata = {'app': APP, 'setup_slack_ns': setup, 'hold_slack_ns': hold,
        'routed_xsa_sha256': digest(xsa), 'build_log_sha256': digest(log),
        'sources_sha256': {name: digest(ROOT/name) for name in files}, 'tile_max_k': 1024, 'tile_max_m': 1024,
        'note': 'Routed build passed timing/DRC; physical qualification is recorded separately.'}
    (out/'build.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print('Compile', APP+'.dts', 'with dtc -@ -I dts -O dtb, then run --finalize')


def finalize(out):
    metadata = json.loads((out/'build.json').read_text())
    if metadata['app'] != APP or metadata['setup_slack_ns'] < .001 or metadata['hold_slack_ns'] < 0:
        raise RuntimeError('Invalid routed build record')
    files = (APP+'.bit.bin', APP+'.dtbo', 'shell.json')
    manifest = {'format_version': 1, 'app': APP, 'clock_hz': 100000000, 'protocol': 'bulk',
        'capture_abi': 'MIC1', 'sample_rate': 16000, 'selection': {'0': 'primary-left', '1': 'primary-right',
        '2': 'secondary-left', '3': 'secondary-right'},
        'files_sha256': {name: digest(out/name) for name in files}, 'build': metadata}
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--bootgen', type=Path)
    p.add_argument('--finalize', action='store_true')
    args = p.parse_args()
    if args.finalize:
        finalize(args.out)
    elif args.bootgen:
        prepare(args.out, args.bootgen)
    else:
        p.error('Supply --bootgen to prepare or --finalize after dtc')
