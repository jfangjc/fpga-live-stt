"""Save a verified, immutable source snapshot without generated build caches."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {
    '.py', '.c', '.cc', '.cpp', '.h', '.hpp', '.v', '.sv', '.vh', '.svh',
    '.tcl', '.sh', '.ps1', '.bat', '.xdc', '.bd', '.xci', '.xpr', '.xml',
    '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.md', '.txt',
    '.bif', '.dts', '.dtsi', '.mem', '.coe', '.rpt',
}
EXCLUDE = {
    '__pycache__', '.git', '.Xil', 'uv-cache', 'linux-tools', 'site-packages',
    'node_modules', 'model-tools', 'xsim.dir',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    if args.destination.exists():
        raise FileExistsError('Refusing to overwrite an existing snapshot')
    payload = {}
    folders = ('rtl', 'hardware', 'sim', 'software', 'scripts', 'deployment',
               'verification', 'research', 'reports', 'Prototype_v2.srcs')
    for folder in folders:
        for directory, children, names in os.walk(ROOT / folder):
            children[:] = [n for n in children if n not in EXCLUDE
                           and not n.startswith('.venv')
                           and not n.endswith(('.cache', '.gen', '.runs', '.sim', '.ip_user_files'))]
            for name in names:
                path = Path(directory) / name
                if path.suffix.lower() in EXTENSIONS or name in ('Makefile', 'Kbuild', 'LICENSE'):
                    payload[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for path in ROOT.iterdir():
        if path.is_file() and path.suffix.lower() in ('.md', '.xpr'):
            payload[path.name] = path.read_bytes()
    freeze = json.loads(payload['reports/fused/shortwide_source_freeze.json'])
    for name, expected in freeze['sources_sha256'].items():
        assert digest((ROOT / name).read_bytes()) == expected, name
    required = ('rtl/experimental/qn_short_wide_axis.sv',
                'rtl/experimental/fused_depthwise_channel_wide.sv',
                'software/ort_fpga_shortwide/pointwise.cc',
                'deployment/experimental-shortwide/qn_tile.c',
                'software/latency/test_short_wide_long_inputs.py',
                'reports/fused/shortwide_long_summary.json',
                'Prototype_v2.srcs/sources_1/bd/asr_v2_system/asr_v2_system.bd')
    assert all(name in payload for name in required)
    readme = '''# Current FPGA ASR source snapshot

Saved 2026-10-11 from C:/Users/jfang/Documents/Vivado/Prototype_v2.
Includes authored RTL, native runtime, Linux driver, Python runtime, build and
test scripts, Vivado project/source configuration, test vectors, and benchmark
evidence. Original and experimental designs are retained together.

Latest physically tested design: shortwide, 32 resident depthwise/pointwise
pairs, 100 MHz, up to 256 feature frames (2.55 seconds).
See SHORT_WIDE_RESULTS.md and LONG_INPUT_RESULTS.md for measured results.

This is a source snapshot. Compiled firmware/libraries, model weights, ONNX
models, recordings, tool installations and build caches are excluded.
The existing FPGA-ASR-short-wide-physical-2026-10-11 and
FPGA-ASR-long-input-tests-2026-10-11 Downloads packages preserve physical
artifacts and associated results. The FPGA-ASR-7pct-verified-2026-10-11
package contains the earlier consolidated model/deployment dependencies.

Extract to a separate directory; Vivado projects can contain absolute paths
that must be adjusted when moving the checkout. Build scripts use Vivado
2026.1 and the KV260 board configuration. Source and evidence hashes are in
SOURCE_MANIFEST.json; archive integrity is in current-source-package.json.
'''
    payload['SOURCE_SNAPSHOT_README.md'] = readme.encode()
    manifest = {'source_root': str(ROOT), 'snapshot_date': '2026-10-11',
                'source_only': True,
                'files': {name: digest(data) for name, data in sorted(payload.items())}}
    payload['SOURCE_MANIFEST.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    args.destination.mkdir(parents=True)
    archive = args.destination / 'prototype-v2-current-source.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as handle:
        for name, data in sorted(payload.items()):
            handle.writestr(name, data)
    with zipfile.ZipFile(archive) as handle:
        assert handle.testzip() is None
        assert set(handle.namelist()) == set(payload)
        for name, data in payload.items():
            assert digest(handle.read(name)) == digest(data), name
    result = {'archive': str(archive), 'sha256': digest(archive.read_bytes()),
              'files': len(payload), 'bytes': archive.stat().st_size,
              'verified': True, 'source_only': True}
    (args.destination / 'current-source-package.json').write_text(json.dumps(result, indent=2) + '\n')
    (args.destination / 'SOURCE_SNAPSHOT_README.md').write_text(readme)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
