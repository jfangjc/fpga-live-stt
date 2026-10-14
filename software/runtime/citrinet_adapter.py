"""Actual resident Citrinet CPU/native-QNC2 benchmark adapter.

Experimental until original-NeMo waveform parity and held-out WER pass.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/model-tools'))
sys.path.insert(0,str(ROOT/'software/native'))
from citrinet_cpu import Frontend,decode,read_audio
from qnc import NativeCachedDevice
from partition import PartitionGraph,options

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as stream:
        for data in iter(lambda:stream.read(1<<20),b''): h.update(data)
    return h.hexdigest()

def bind_validation_reports(metadata):
    """Validation flags default false; opt-in reports must bind current artifacts."""
    metadata.update(original_nemo_wrapper_validated=False,original_model_output_parity_validated=False,
                    physical_quantized_graph_parity_validated=False)
    identity=('model_sha256','tokenizer_sha256','preprocessing_id','decoder_id')
    original=os.environ.get('NEMO_VALIDATION_REPORT') or os.environ.get('CITRINET_ORIGINAL_PARITY_REPORT')
    if not original:
        defaults=[ROOT/'reports/nemo_full_validation.json',ROOT/'research/export/citrinet-256-ls/nemo_full_validation.json']
        original=next((str(path) for path in defaults if path.is_file()),None)
    if original:
        report=json.loads(Path(original).read_text())
        original_identity=identity+('checkpoint_sha256','frontend_constants_sha256','frontend_source_sha256','decoder_sha256')
        if (report.get('status')!='pass' or report.get('complete_original_nemo_wrapper_validated') is not True or
            not report.get('tests') or any(not metadata.get(k) or report.get(k)!=metadata[k] for k in original_identity)):
            raise ValueError('Original model parity report is missing, failed or for different artifacts')
        metadata['original_nemo_wrapper_validated']=True
        metadata['original_model_output_parity_validated']=True
        metadata['original_model_output_parity_report_sha256']=digest(original)
    physical=os.environ.get('CITRINET_PHYSICAL_PARITY_REPORT')
    if physical and metadata['hardware_execution']:
        report=json.loads(Path(physical).read_text());proof=report.get('physical_vs_numerical_int8_implementation_parity',{})
        recorded=report.get('metadata',{})
        dma=report.get('dma',{})
        checks=('passed','positive_physical_dma_work','shapes_equal','finite','encoded_lengths_equal',
                'encoded_lengths_valid','logits_within_tolerance','transcripts_match')
        if (report.get('hardware_execution') is not True or any(proof.get(k) is not True for k in checks) or
            proof.get('absolute_tolerance')!=1e-4 or proof.get('relative_tolerance')!=1e-5 or
            proof.get('positive_physical_dma_work') is not True or
            not all(isinstance(dma.get(k),(int,float)) and np.isfinite(dma[k]) and dma[k]>0
                    for k in ('loads','runs','ioctls','tx_bytes','rx_bytes')) or
            any(recorded.get(k)!=metadata[k] for k in identity+('native_library_sha256','source_sha256'))):
            raise ValueError('Physical INT8 parity report is missing, failed or for different artifacts/binary/source')
        metadata['physical_quantized_graph_parity_validated']=True
        metadata['physical_quantized_graph_parity_report_sha256']=digest(physical)

class Runner:
    def __init__(self,mode,threads,model_dir=None):
        if mode not in ('cpu','fpga','emulate'): raise ValueError('Unknown mode')
        self.mode,self.threads=mode,threads
        self.model_dir=Path(model_dir or os.environ.get('CITRINET_MODEL_DIR',ROOT/'research/export/citrinet-256-ls'))
        self.frontend=Frontend(self.model_dir)
        self.vocab=(self.model_dir/'vocab.txt').read_text(encoding='utf-8').splitlines()
        self.device=None
        if mode=='cpu':
            self.graph=ort.InferenceSession(str(self.model_dir/'model.onnx'),options(threads),providers=['CPUExecutionProvider'])
        else:
            if mode=='fpga': self.device=NativeCachedDevice(os.environ.get('QNC_DEVICE','/dev/qn-tile'))
            try: self.graph=PartitionGraph(self.model_dir/'model.onnx',threads,self.device,mode=='emulate',int(os.environ.get('ORT_CPU_REGION_THREADS','1')))
            except BaseException:
                self.close(); raise
        try:
            frontend_identity=hashlib.sha256((digest(self.model_dir/'frontend.npz')+digest(ROOT/'software/model-tools/citrinet_cpu.py')).encode()).hexdigest()
            self._metadata={'model_sha256':digest(self.model_dir/'model.onnx'),
                'tokenizer_sha256':digest(self.model_dir/'vocab.txt'),'preprocessing_id':frontend_identity,
                'decoder_id':digest(ROOT/'software/model-tools/citrinet_cpu.py'),
                'threads':threads,'hardware_execution':mode=='fpga','precision':'FP32' if mode=='cpu' else 'dynamic symmetric INT8 pointwise/INT32 sums + FP32 CPU regions',
                'calibration_audio_sha256':[],'onnxruntime_version':ort.__version__,
                'original_nemo_wrapper_validated':False,'accelerated_nodes':getattr(self.graph,'accelerated_nodes',[]),
                'cpu_region_threads':int(os.environ.get('ORT_CPU_REGION_THREADS','1')) if mode!='cpu' else threads,
                'native_library_sha256':digest(ROOT/'software/native/libqnc.so') if self.device else None}
            archive=Path(os.environ.get('CITRINET_CHECKPOINT',ROOT/'research/checkpoints/citrinet-256-ls/stt_en_citrinet_256_ls.nemo'))
            self._metadata['checkpoint_sha256']=digest(archive) if archive.is_file() else None
            self._metadata['frontend_constants_sha256']=digest(self.model_dir/'frontend.npz')
            self._metadata['frontend_source_sha256']=digest(ROOT/'software/model-tools/citrinet_cpu.py')
            self._metadata['decoder_sha256']=self._metadata['decoder_id']
            self._metadata['thread_environment']={k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')}
            self._metadata['source_sha256']={str(path.relative_to(ROOT)):digest(path) for path in (
                ROOT/'software/model-tools/citrinet_cpu.py',Path(__file__),ROOT/'software/runtime/partition.py',
                ROOT/'software/native/qnc.py',ROOT/'software/native/qnc.c',ROOT/'software/native/qnc.h')}
            bind_validation_reports(self._metadata)

        except BaseException:
            self.close(); raise

    def metadata(self): return dict(self._metadata)

    def transcribe(self,path):
        start=time.perf_counter(); audio=read_audio(path); loaded=time.perf_counter()
        features,lengths=self.frontend(audio); front=time.perf_counter()
        feed={'features':features,'feature_lengths':lengths}
        before=self.device.stats() if self.device else None
        outputs=self.graph.run(None,feed) if self.mode=='cpu' else self.graph.run(feed)
        inferred=time.perf_counter()
        logits,encoded=outputs
        text=decode(logits[0],encoded[0],self.vocab); ended=time.perf_counter()
        result={'transcript':text,'audio_seconds':len(audio)/16000,'load_seconds':loaded-start,
            'frontend_seconds':front-loaded,'inference_seconds':inferred-front,'decode_seconds':ended-inferred,
            'total_seconds':ended-start,'encoded_length':int(encoded[0]),'hardware_execution':self.mode=='fpga'}
        if self.device:
            result['dma']={k:v-before[k] for k,v in self.device.stats().items()}
        if self.mode!='cpu': result['partition_profile']=self.graph.last_profile
        return result

    def close(self):
        if self.device: self.device.close(); self.device=None
        self.graph=None

def create_runner(mode,threads): return Runner(mode,threads)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('wav');p.add_argument('--mode',choices=['cpu','fpga','emulate'],default='cpu')
    p.add_argument('--threads',type=int,default=4);p.add_argument('--model-dir');p.add_argument('--runs',type=int,default=20)
    p.add_argument('--warmups',type=int,default=3);p.add_argument('--output',type=Path)
    a=p.parse_args();start=time.perf_counter();r=Runner(a.mode,a.threads,a.model_dir);setup=time.perf_counter()-start
    try:
        if a.runs<1 or a.warmups<0: p.error('runs must be positive and warmups nonnegative')
        for _ in range(a.warmups): r.transcribe(a.wav)
        runs=[r.transcribe(a.wav) for _ in range(a.runs)]
        totals=[run['total_seconds'] for run in runs]
        report={'initialization_seconds':setup,'metadata':r.metadata(),'warmups':a.warmups,'runs':runs,
                'p50_seconds':float(np.percentile(totals,50)),'p95_seconds':float(np.percentile(totals,95))}
        content=json.dumps(report,indent=2)
        if a.output: a.output.write_text(content+'\n')
        print(content)
    finally: r.close()
