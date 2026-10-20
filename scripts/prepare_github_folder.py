"""Copy the selected KV260 implementation into a separate source distribution."""
import ast
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'kv260-asr-github'


def copy(source, destination=None):
    target = OUT/(destination or source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT/source, target)


def main():
    if OUT.exists():
        raise SystemExit('Refusing to overwrite the GitHub folder')
    OUT.mkdir()
    for name in ('qn_mac.v', 'sph0645_rx.v', 'voice_axi.v'):
        copy('rtl/'+name)
    for name in ('voice_axi_inference.v', 'qn_branch512_ab_pw_core.v', 'fused_affine_quant_drop_pipe.sv',
                 'fused_affine_quant_select_wrap.sv', 'fused_depthwise_droppipe.sv',
                 'qn_branch512_ab_inner.sv', 'qn_branch512_ab_axis.sv', 'qn_bulk_axis.v', 'fused_affine_quant.v'):
        copy('rtl/experimental/'+name)
    copy('hardware/mic_cdc.xdc')
    copy('build/generated/asr_v2_top.v', 'hardware/reference/asr_v2_top.v')
    base = 'build/branch512_ab166_system/Prototype_v3_branch512_ab166.srcs/'
    copy(base+'constrs_1/imports/Lab2b-Files/kria-constraints.xdc', 'hardware/reference/kria-constraints.xdc')
    directory = ROOT/base/'sources_1/bd/asr_v2_system'
    for path in directory.rglob('*'):
        if path.is_file() and path.suffix in ('.bd', '.xci', '.xml'):
            copy(path.relative_to(ROOT).as_posix(), 'hardware/reference/asr_v2_system/'+path.relative_to(directory).as_posix())
    for name in ('ab_mac_conformance', 'branch512_ab_fast_sim', 'branch512_ab_reset_sim', 'branch512_ab_payload_reset_sim'):
        copy('scripts/'+name+'.tcl')
    copy('scripts/vivado_four_threads.tcl')
    for name in ('tb_ab_mac_conformance.sv', 'tb_qn_branch512_ab_axis.sv',
                 'tb_qn_branch512_ab_reset.sv', 'tb_qn_branch512_ab_payload_reset.sv', 'qn_mac_ab_model.sv'):
        copy('sim/'+name)
    copy('sim/fast/qn_branch512_ab_pw_core.v')
    for name in ('boundary_lut.py', 'boundary_lut.cc', 'libboundary_lut.so', 'residual_tail.py',
                 'residual_tail.cc', 'libresidual_tail.so', 'residual_tail_maskfast.cc', 'libresidual_tail_maskfast.so',
                 'se_pool.py', 'se_pool.cc', 'libse_pool.so', 'split_scale_pairs.py', 'retain_stride_pointwise.py'):
        copy('software/latency/'+name)
    for name in ('pointwise.cc', 'qnc.h', 'qnc_transport.c', 'libort_fpga.so', 'build.sh',
                 'pair_graph.py', 'branch_graph.py', 'stream_graph.py'):
        copy('software/ort_fpga_stream_branch512_neon/'+name)
    for directory in ('software/ort_fpga_stream_branch512_neon/include', 'software/ort_fpga_shortwide/include'):
        for path in (ROOT/directory).glob('*.h'):
            copy(path.relative_to(ROOT).as_posix())
    copy('software/requirements-runtime.txt', 'requirements.txt')
    for role, directory in (('bulk', 'deployment/experimental-bulk'), ('branch', 'deployment/experimental-stream-branch')):
        for path in (ROOT/directory).iterdir():
            if path.suffix in ('.c', '.h') or path.name == 'Makefile':
                copy(path.relative_to(ROOT).as_posix(), 'drivers/'+role+'/'+path.name)
    copy('deployment/kernel-compat/6.8.0-1036-xilinx/bulk/qn_tile.ko', 'drivers/prebuilt/6.8.0-1036-xilinx/bulk/qn_tile.ko')
    copy('deployment/experimental-stream-branch/qn_tile.ko', 'drivers/prebuilt/6.8.0-1036-xilinx/branch/qn_tile.ko')
    for app in ('asr-v3-bulk', 'asr-v3-branch512-ab166'):
        for path in (ROOT/'deployment'/app).iterdir():
            if path.name.endswith(('.bit.bin', '.dtbo', '.dts', '.bif')) or path.name == 'shell.json':
                copy(path.relative_to(ROOT).as_posix(), 'firmware/'+app+'/'+path.name)
    for name in ('frontend.npz', 'vocab.txt'):
        copy('research/export/citrinet-256-ls/'+name, 'models/citrinet-256/'+name)
    copy('research/fused/cpu-int8-cse.onnx', 'models/citrinet-256/cpu-int8-cse.onnx')
    # Preserve the exact frontend, WAV conversion and decoder arithmetic.
    original = ROOT/'software/model-tools/citrinet_cpu.py'
    candidate = ROOT/'software/latency/frontend_valid_frames.py'
    def extract(path, names):
        text = path.read_text()
        return '\n\n'.join(ast.get_source_segment(text,n) for n in ast.parse(text).body
            if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in names)
    text = '"""Pinned Citrinet frontend and WordPiece decoder."""\nimport wave\nfrom pathlib import Path\nimport numpy as np\n\n'
    text += extract(original, {'Frontend', 'read_audio', 'decode'})+'\n\n'+extract(candidate, {'ValidFrameFrontend'})+'\n'
    target = OUT/'software/mvp/frontend.py'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline='\n')
    policy = json.loads((ROOT/'reports/fused/branch512_ab166_vf_latency_policy.json').read_text())
    (OUT/'config').mkdir()
    (OUT/'config/policies.json').write_text(json.dumps({'selected': policy['selected'], 'cpu_policies': policy['cpu_policies']},indent=2)+'\n')
    (OUT/'evidence').mkdir()
    report = json.loads((ROOT/'reports/mvp/clean_board_test.json').read_text())
    public = {key:report[key] for key in ('date','board','clean_software_installation','fresh_branch_firmware_installation',
        'full_warm_logit_comparisons','twofold_speed_acceptance','warm_contexts','dependencies','capture_qualified','representative_wer_qualified')}
    public['scope'] = 'Original MVP clean-board measurements. Public runtime needs its own physical verification.'
    public['cold_initialization_seconds'] = [r['initialization_seconds'] for r in report['physical_smoke_tests']]
    public['cold_processing_seconds'] = [r['processing_seconds'] for r in report['physical_smoke_tests']]
    (OUT/'evidence/mvp-1.0.1-summary.json').write_text(json.dumps(public,indent=2)+'\n')
    print('Created', OUT)


if __name__ == '__main__':
    main()
