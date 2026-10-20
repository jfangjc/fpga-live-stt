"""Apply the bounded KV260 matrix hook to pinned whisper.cpp v1.8.3."""
import argparse
from pathlib import Path
import shutil
import subprocess

PIN = '2eeeba56e9edd762b4b38467bab96c2517163158'


def patch(upstream, project):
    head = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    if head != PIN:
        raise ValueError(f'Expected {PIN}, got {head}')
    cpu = upstream / 'ggml/src/ggml-cpu'
    model_path = upstream / 'src/whisper.cpp'
    model_source = model_path.read_text()
    naming = '        ggml_set_name(tensor, format(ASR_TENSOR_NAMES.at(system).at(type), layer).c_str());'
    if naming not in model_source:
        anchor = '        model.tensors[format(ASR_TENSOR_NAMES.at(system).at(type), layer)] = tensor;'
        if model_source.count(anchor) != 1:
            raise ValueError('Unexpected upstream weight loader')
        model_path.write_text(model_source.replace(anchor, anchor+'\n'+naming))
    # CPU repacked buffers have a private layout and cannot be read as GGML rows.
    # Only FPGA-read weights need ordinary rows. Retain optimized CPU layouts
    # for autoregressive decoding; its cost grows with the output token count.
    model_source = model_path.read_text()
    allocation = '        ggml_backend_buffer_type_t buft = select_weight_buft(hparams, meta, op, buft_list);'
    replacement = ('        ggml_backend_buffer_type_t buft = getenv("WHISPER_KV260") && '
                   'strcmp(getenv("WHISPER_KV260"), "1") == 0 ? ggml_backend_cpu_buffer_type() : '
                   'select_weight_buft(hparams, meta, op, buft_list);')
    if 'kv260_weight_name' not in model_source:
        model_source = model_source.replace(replacement,allocation)
        selective = '''        const std::string kv260_weight_name = format(ASR_TENSOR_NAMES.at(system).at(type), layer);
        const char * kv260_enabled = getenv("WHISPER_KV260");
        const char * kv260_decode = getenv("WHISPER_KV260_DECODE");
        const bool kv260_plain = kv260_enabled && strcmp(kv260_enabled, "1") == 0 && (
            kv260_weight_name.rfind("encoder.", 0) == 0 ||
            kv260_weight_name.find(".cross_attn.key.weight") != std::string::npos ||
            kv260_weight_name.find(".cross_attn.value.weight") != std::string::npos ||
            (kv260_decode && strcmp(kv260_decode, "1") == 0));
        ggml_backend_buffer_type_t buft = kv260_plain ? ggml_backend_cpu_buffer_type() : select_weight_buft(hparams, meta, op, buft_list);'''
        if allocation not in model_source:
            raise ValueError('Unexpected upstream buffer selection')
        model_path.write_text(model_source.replace(allocation,selective,1))
    path = cpu / 'ggml-cpu.c'
    source = path.read_text()
    marker = '#include "kv260-matmul.h"'
    if marker not in source:
        needle = '    const struct ggml_tensor * src0 = dst->src[0];'
        start = source.index('void ggml_compute_forward_mul_mat(')
        offset = source.index(needle, start)
        source = source[:offset] + '    if (kv260_mul_mat(params, dst)) return;\n\n' + source[offset:]
        source = source.replace('// ggml_compute_forward_mul_mat\n', marker + '\n\n// ggml_compute_forward_mul_mat\n', 1)
        path.write_text(source)
    shutil.copyfile(project / 'software/whisper/kv260-direct.h',cpu / 'kv260-matmul.h')
    # Reuse the generic QNC2 transport, with its larger bulk-driver DMA capacity.
    transport = (project / 'software/ort_fpga_bulk/qnc_transport.c').read_text()
    extension = (project / 'software/whisper/qnc_ggml.inc').read_text()
    (cpu / 'qnc_transport.c').write_text(transport+'\n'+extension)
    header = (project / 'software/ort_fpga_bulk/qnc.h').read_text()
    declaration = ('typedef void (*qnc_barrier_fn)(void *);\n'
                   'int qnc_run_ggml(qnc *, const float *, size_t, size_t, const float *, float *, size_t);\n'
                   'int qnc_run_ggml_parallel(qnc *, const float *, size_t, size_t, const float *, float *, '
                   'size_t, int, unsigned, unsigned, qnc_barrier_fn, void *);\n')
    (cpu / 'qnc.h').write_text(header.replace('#endif',declaration+'#endif'))
    cmake = cpu / 'CMakeLists.txt'
    content = cmake.read_text()
    addition = '\n    target_sources(${GGML_CPU_NAME} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/ggml-cpu/qnc_transport.c)\n'
    content = content.replace('${CMAKE_CURRENT_SOURCE_DIR}/qnc_transport.c',
                              '${CMAKE_CURRENT_SOURCE_DIR}/ggml-cpu/qnc_transport.c')
    if addition not in content:
        anchor = '    add_library(${GGML_CPU_NAME}'
        # add_library is provided by ggml_add_backend_library in this version.
        anchor = '    ggml_add_backend_library(${GGML_CPU_NAME}'
        i = content.index(anchor)
        end = content.index('\n', content.index(')', i))
        content = content[:end] + addition + content[end:]
    options = '\n    set_source_files_properties(${CMAKE_CURRENT_SOURCE_DIR}/ggml-cpu/qnc_transport.c PROPERTIES COMPILE_OPTIONS "-fno-fast-math;-ffp-contract=off")\n'
    if options not in content:
        content = content.replace(addition,addition+options)
    cmake.write_text(content)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('upstream', type=Path)
    ap.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[2])
    a = ap.parse_args()
    patch(a.upstream.resolve(), a.project.resolve())
