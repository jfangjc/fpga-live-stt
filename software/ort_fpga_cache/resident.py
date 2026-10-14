"""Experimental resident audio API for a physically verified four-pair graph."""
import ctypes
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import onnx
import onnxruntime as ort

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
sys.path.insert(0,str(ROOT/'software/latency'))
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
from common import Frontend,identity,sha
from probe import stats
from dma_irq import verify

spec=importlib.util.spec_from_file_location('_accepted_resident_base',ROOT/'software/latency/resident.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)


class CacheResidentTranscriber(base.ResidentTranscriber):
    """Initialize once, then transcribe finite float32 16-kHz arrays in memory.

    A completed physical benchmark binds the experiment. It does not itself
    certify a latency gain. Accuracy evidence is diagnostic; prefix text remains
    provisional. Hardware failures propagate without CPU fallback.
    """
    def __init__(self,benchmark,backend='fpga'):
        started=time.perf_counter();benchmark=Path(benchmark).resolve()
        if backend not in ('cpu','fpga'):raise ValueError('backend must be cpu or fpga')
        proof=json.loads(benchmark.read_text())
        if not(proof.get('complete') and proof.get('hardware_execution') and proof.get('runtime')=='cache'):
            raise ValueError('A completed physical cache benchmark is required')
        if len(proof['contexts'])!=1 or not proof['contexts'][0]['physical_oracle_bit_parity']:
            raise ValueError('Expected one measured context with exact hardware parity')
        if proof['feature_padding_policy']!='trim_to_valid' or proof['cpu_threads']!=4 or proof['main_core']!=3 or proof['worker_cores']!=[0,1,2]:
            raise ValueError('Unsupported measured execution policy')
        model=ROOT/'research/fused/cpu-int8-cse.onnx'
        directory=ROOT/'research/export/citrinet-256-ls'
        cpu=json.loads(model.with_suffix('.json').read_text())
        if sha(model)!=proof['cpu_model_sha256'] or sha(model)!=cpu['model_sha256'] or identity(directory)!=cpu['source_identity']:
            raise ValueError('CPU model/frontend/checkpoint identity mismatch')
        cse_path=ROOT/'reports/fused/cse_arm_validation.json';cse=json.loads(cse_path.read_text())
        if not(cse['complete'] and cse['all_logits_bit_exact'] and cse['cse_model_sha256']==sha(model)):
            raise ValueError('Missing CSE numerical validation')
        if cpu['parent_model_sha256']!=sha(ROOT/'research/fused/cpu-int8.onnx'):
            raise ValueError('CPU quantization parent mismatch')
        for key,name in [('transform_source_sha256','eliminate_duplicates.py'),('shape_proof_source_sha256','share_shape_metadata.py')]:
            if cpu[key]!=sha(ROOT/'software/latency'/name):raise ValueError('CSE source mismatch')
        validation_path=ROOT/'reports/fused/cache_physical_validation.json'
        validation=json.loads(validation_path.read_text())
        if sha(validation_path)!=proof['validation_sha256'] or not(validation['complete'] and validation['hardware_execution']):
            raise ValueError('Physical validation binding mismatch')
        if validation['model_sha256']!=sha(model) or validation['source_sha256']!=sha(Path(__file__).with_name('validate.py')) or validation['graph_source_sha256']!=sha(Path(__file__).with_name('graph.py')):
            raise ValueError('Physical validation source/model mismatch')
        if not all(r['length_exact'] and r['physical_oracle_bit_parity'] and r['texts']['cpu']==r['texts']['fpga'] for r in validation['clips']):
            raise ValueError('Missing diagnostic physical transcript/length parity')
        graph_path=benchmark.with_suffix('.onnx')
        if sha(graph_path)!=proof['fpga_graph_sha256'] or sha(graph_path)!=validation['fpga_graph_sha256']:
            raise ValueError('Physical graph identity mismatch')
        graph=onnx.load(graph_path)
        self.nodes=[n.name for n in graph.graph.node if n.domain=='prototype.fpga.cache' and n.op_type=='FpgaDepthwisePointwise']
        if len(self.nodes)!=4:raise ValueError('Expected four physical retained pairs')
        self.backend=backend;self.lock=threading.Lock();self.padding_policy='trim_to_valid'
        self.main_core=3;self.dma_irq_core=proof['dma_irq_core'];self.lib=None
        spin=proof['contexts'][0]['spin_duration_us']
        opt=ort.SessionOptions();opt.intra_op_num_threads=4;opt.inter_op_num_threads=1
        opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        for key,value in [('session.intra_op.allow_spinning','1' if spin else '0'),
                          ('session.inter_op.allow_spinning','0'),
                          ('session.intra_op.spin_duration_us',str(spin)),
                          ('session.intra_op.spin_backoff_max','8'),
                          ('session.intra_op_thread_affinities','1;2;3')]:opt.add_session_config_entry(key,value)
        if backend=='fpga':
            library=Path(__file__).with_name('libort_fpga.so')
            firmware=Path('/lib/firmware/xilinx/asr-v3-cache/asr-v3-cache.bit.bin')
            clock=Path('/sys/bus/platform/devices/asr-v3-cache-clock/set_rate')
            driver=ROOT/'deployment/experimental-cache/qn_tile.ko'
            for artifact,key in [(library,'library_sha256'),(firmware,'firmware_sha256'),(driver,'driver_sha256')]:
                if sha(artifact)!=proof[key] or sha(artifact)!=validation[key]:raise ValueError('Physical artifact identity mismatch')
            if int(clock.read_text())!=proof['pl_clock_hz']:raise ValueError('Physical clock mismatch')
            verify(self.dma_irq_core);self.lib=ctypes.CDLL(str(library.resolve()));self.stats=stats
            opt.register_custom_ops_library(str(library.resolve()))
        else:graph=onnx.load(model)
        with self._placement():self.runner=ort.InferenceSession(onnx.shape_inference.infer_shapes(graph).SerializeToString(),opt,providers=['CPUExecutionProvider'])
        self.frontend=Frontend(directory);self.vocab=(directory/'vocab.txt').read_text().splitlines()
        self.initialization_seconds=time.perf_counter()-started
        self.policy={'threads':4,'spin_duration_us':spin,'main_core':3,'worker_cores':[0,1,2],
                     'feature_padding_policy':self.padding_policy,'dma_irq_core':self.dma_irq_core,
                     'experiment':'four_resident_pairs'}
