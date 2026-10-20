"""Package fresh v2 artifacts only; never modify the working v1 deployment."""
import hashlib
import json
import os
import struct
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    audit = json.loads((ROOT / 'verification/v2_hardware_audit.json').read_text())
    if not audit['complete']:
        raise RuntimeError('Fresh routed hardware audit must pass before packaging firmware')
    for relative, expected in audit['sources_sha256'].items():
        if sha(ROOT / relative) != expected:
            raise RuntimeError('Hardware source changed after audit: ' + relative)
    firmware = ROOT / 'deployment/asr-v2'
    required = ['asr-v2.bit.bin', 'asr-v2.dtbo', 'shell.json']
    if any(not (firmware / name).is_file() for name in required):
        raise RuntimeError('Bootgen/overlay firmware package is incomplete')
    if (firmware / 'asr-v2.bit.bin').stat().st_size < 100000:
        raise RuntimeError('Firmware binary is unexpectedly small')
    routed = ROOT / 'Prototype_v2.runs/impl_1/asr_v2_top.bit'
    if sha(firmware / 'asr-v2.bit') != sha(routed):
        raise RuntimeError('Firmware bitstream differs from audited routed build')
    if (firmware / 'asr-v2.bit.bin').stat().st_mtime < routed.stat().st_mtime:
        raise RuntimeError('Raw firmware binary predates routed bitstream')
    for overlay in audit['overlays']:
        if sha(ROOT / overlay['path']) != overlay['sha256']:
            raise RuntimeError('Overlay source changed after hardware audit')
    if (firmware / 'asr-v2.dtbo').stat().st_mtime < (ROOT / 'deployment/asr-v2.dts').stat().st_mtime:
        raise RuntimeError('Device tree binary predates its source')
    if (firmware / 'asr-v2.dtbo').read_bytes()[:4] != bytes.fromhex('d00dfeed'):
        raise RuntimeError('Invalid DTBO')
    if json.loads((firmware / 'shell.json').read_text())['shell_type'] != 'PL_FLAT':
        raise RuntimeError('Incorrect shell type')
    module = ROOT / 'deployment/driver/6.8.0-1015-xilinx/qn_tile_cached.ko'
    data = module.read_bytes()
    if struct.unpack_from('<H', data, 18)[0] != 183 or b'6.8.0-1015-xilinx SMP preempt mod_unload modversions aarch64' not in data:
        raise RuntimeError('Wrong driver architecture or kernel')
    simulation = ROOT / 'reports/cached_sim.log'
    if 'PASS: 69 cached arithmetic/protocol/reset cases' not in simulation.read_text():
        raise RuntimeError('Cached RTL simulation did not pass')
    if simulation.stat().st_mtime < max((ROOT / n).stat().st_mtime for n in ('rtl/qn_cached_axis.v', 'sim/tb_qn_cached_axis.sv')):
        raise RuntimeError('Stale simulation')
    original_path = ROOT / 'reports/nemo_full_validation.json'
    original = json.loads(original_path.read_text())
    if (original.get('status') != 'pass' or not original.get('complete_original_nemo_wrapper_validated')
            or original.get('original_configured_ctc_decoder_executed') is not True or not original.get('tests')):
        raise RuntimeError('Complete original NeMo validation must pass')
    for relative, key in (
        ('research/checkpoints/citrinet-256-ls/stt_en_citrinet_256_ls.nemo', 'checkpoint_sha256'),
        ('research/export/citrinet-256-ls/model.onnx', 'model_sha256'),
        ('research/export/citrinet-256-ls/vocab.txt', 'tokenizer_sha256'),
        ('research/export/citrinet-256-ls/frontend.npz', 'frontend_npz_sha256'),
        ('software/model-tools/citrinet_cpu.py', 'citrinet_cpu_source_sha256'),
        ('software/model-tools/validate_nemo.py', 'validate_nemo_source_sha256')):
        if sha(ROOT / relative) != original.get(key):
            raise RuntimeError('Original model parity is stale: ' + relative)
    files = []
    for directory in ['rtl', 'sim', 'scripts', 'hardware', 'software', 'verification', 'deployment', 'reports']:
        for parent, directories, names in os.walk(ROOT / directory):
            directories[:] = [d for d in directories if not d.startswith('.venv') and d not in ('__pycache__', 'linux-tools')]
            for name in names:
                p = Path(parent) / name
                rel = p.relative_to(ROOT)
                if rel.as_posix() in ('deployment/PACKAGE_SHA256SUMS', 'reports/package.json'):
                    continue
                if p.suffix in ('.pyc', '.o') or p.name in ('libqnc.so', 'libqnc_aarch64.so', 'test_qnc', 'test_qnc_sanitized', 'test_qnc_independent') and 'prebuilt' not in rel.parts:
                    continue
                files.append(p)
    for name in ['research/citrinet_inspection.json', 'research/citrinet_hf_metadata.json', 'research/reference_speech.wav']:
        p = ROOT / name
        if p.exists():
            files.append(p)
    files.extend(p for p in (ROOT / 'research').glob('*') if p.is_file() and p.suffix in ('.py', '.md', '.json'))
    for directory in ['research/export', 'research/eval', 'research/checkpoints']:
        if (ROOT / directory).exists():
            files.extend(p for p in (ROOT / directory).rglob('*') if p.is_file())
    for name in ['README.md', 'RESULTS.md']:
        files.append(ROOT / name)
    files = sorted(set(files))
    entries = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in files}
    sums = ''.join(f'{digest}  {name}\n' for name, digest in entries.items())
    (ROOT / 'deployment/PACKAGE_SHA256SUMS').write_text(sums)
    target = ROOT / 'prototype-v2-package.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for p in files:
            archive.write(p, 'prototype-v2-package/' + str(p.relative_to(ROOT)).replace('\\', '/'))
        archive.writestr('prototype-v2-package/SHA256SUMS', sums)
    report = dict(zip_sha256=sha(target), files=len(entries), firmware_source_audit_passed=True,
                  original_nemo_validation_passed=True, original_nemo_report_sha256=sha(original_path),
                  physical_board_validation=False, accuracy_gate_passed=False,
                  speedup_gate_passed=False, package=str(target))
    (ROOT / 'reports/package.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
