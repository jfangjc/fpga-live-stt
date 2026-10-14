"""Artifact-bound graph and corpus utilities for the staged fused experiment."""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import numpy as np
import onnx
from onnx import helper, numpy_helper
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'software/model-tools'))
sys.path.insert(0, str(ROOT / 'software/evaluation'))
from citrinet_cpu import Frontend, read_audio, decode
from benchmark import errors, environment as base_environment


def environment():
    result = base_environment()
    def read(path):
        try:
            return path.read_text().strip()
        except OSError:
            return None
    result['hwmon_temperature_millicelsius'] = {str(p): read(p) for p in Path('/sys/class/hwmon').glob('hwmon*/temp*_input')}
    result['iio_temperature_attributes'] = {str(p): read(p) for p in Path('/sys/bus/iio/devices').glob('iio:device*/in_temp*') if p.is_file()}
    result['cpu_frequency_bounds_khz'] = {str(p): read(p) for pattern in ('cpu*/cpufreq/scaling_min_freq', 'cpu*/cpufreq/scaling_max_freq')
                                          for p in Path('/sys/devices/system/cpu').glob(pattern)}
    return result


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def session(model, threads=4, profile=None, optimize=True):
    opt = ort.SessionOptions()
    opt.intra_op_num_threads = threads
    opt.inter_op_num_threads = 1
    opt.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opt.graph_optimization_level = (ort.GraphOptimizationLevel.ORT_ENABLE_ALL if optimize
                                    else ort.GraphOptimizationLevel.ORT_DISABLE_ALL)
    if profile:
        opt.enable_profiling = True
        opt.profile_file_prefix = str(profile)
    source = model.SerializeToString() if isinstance(model, onnx.ModelProto) else str(model)
    return ort.InferenceSession(source, opt, providers=['CPUExecutionProvider'])


def corpus(path, role):
    records = []
    ids, hashes = set(), set()
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get('split', record.get('role')) not in role:
            raise ValueError('Incorrect corpus role: ' + record['id'])
        audio = Path(path).parent / record['audio']
        digest = sha(audio)
        if record['id'] in ids or digest in hashes:
            raise ValueError('Duplicate corpus ID/audio')
        if record.get('wav_sha256', digest) != digest:
            raise ValueError('Audio hash mismatch: ' + str(audio))
        ids.add(record['id']); hashes.add(digest)
        records.append(dict(record, path=audio, audio_sha256=digest))
    if not records:
        raise ValueError('Empty corpus')
    return records


def calibration_tensors(model):
    infos = {v.name: v for v in list(model.graph.input) + list(model.graph.value_info)}
    names = set()
    for node in model.graph.node:
        if node.op_type == 'Conv':
            names.update([node.input[0], node.output[0]])
        elif node.op_type in ('Where', 'Relu', 'Mul', 'Add'):
            name = node.output[0]
            info = infos.get(name)
            if (info is not None and info.type.tensor_type.elem_type == onnx.TensorProto.FLOAT
                    and len(info.type.tensor_type.shape.dim) == 3):
                names.add(name)
    return sorted(names)


def expose(model, names):
    result = copy.deepcopy(model)
    infos = {v.name: v for v in list(model.graph.input) + list(model.graph.value_info)
             + list(model.graph.output)}
    existing = {v.name for v in result.graph.output}
    for name in names:
        if name not in existing:
            result.graph.output.append(copy.deepcopy(infos[name]))
    return result


def block_id(name):
    match = re.search(r'/encoder/encoder\.(\d+)/', name)
    return int(match.group(1)) if match else None


def blocks(model):
    nodes = list(model.graph.node)
    initial = {v.name for v in model.graph.initializer}
    result = []
    for index in sorted({block_id(n.name) for n in nodes} - {None}):
        subset = [n for n in nodes if block_id(n.name) == index]
        produced = {v for n in subset for v in n.output}
        required = {v for n in subset for v in n.input if v}
        consumed_elsewhere = {v for n in nodes if block_id(n.name) != index for v in n.input}
        consumed_elsewhere.update(v.name for v in model.graph.output)
        inputs = sorted(required - produced - initial)
        outputs = sorted(produced & consumed_elsewhere)
        result.append({'id': index, 'inputs': inputs, 'outputs': outputs,
                       'convolutions': sum(n.op_type == 'Conv' for n in subset),
                       'global_se': any(n.op_type == 'Sigmoid' for n in subset),
                       'node_names': [n.name for n in subset]})
    return result


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def identity(model_dir):
    result = {name: sha(Path(model_dir) / name) for name in ('model.onnx', 'frontend.npz', 'vocab.txt')}
    result['frontend_decoder_source'] = sha(ROOT/'software/model-tools/citrinet_cpu.py')
    result['wer_source'] = sha(ROOT/'software/evaluation/benchmark.py')
    return result


def sources():
    return {p.name: sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))}
