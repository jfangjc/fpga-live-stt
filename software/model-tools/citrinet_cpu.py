#!/usr/bin/env python3
"""Resident CPU baseline with checkpoint-specific features and WordPiece CTC.

Frontend follows pinned NeMo v1.23.0 eval behavior. Model acceptance requires
full-NeMo waveform parity; see validate_nemo.py and export_validation.json.
"""
import argparse
import hashlib
import json
import os
import re
import time
import wave
from pathlib import Path
import numpy as np
import onnxruntime as ort

DEFAULT_MODEL = Path(__file__).resolve().parents[2]/'research/export/citrinet-256-ls'


def original_validation(model_dir):
    root=Path(__file__).resolve().parents[2]
    path=Path(os.environ.get('NEMO_VALIDATION_REPORT',root/'reports/nemo_full_validation.json'))
    try:
        proof=json.loads(path.read_text())
        sha=lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        source=sha(__file__); frontend=sha(Path(model_dir)/'frontend.npz')
        matches={'model_sha256':sha(Path(model_dir)/'model.onnx'),
            'tokenizer_sha256':sha(Path(model_dir)/'vocab.txt'),
            'checkpoint_sha256':sha(root/'research/checkpoints/citrinet-256-ls/stt_en_citrinet_256_ls.nemo'),
            'frontend_constants_sha256':frontend,'frontend_source_sha256':source,'decoder_sha256':source,
            'preprocessing_id':hashlib.sha256((frontend+source).encode()).hexdigest(),'decoder_id':source}
        return (proof.get('status')=='pass' and proof.get('complete_original_nemo_wrapper_validated') is True
            and bool(proof.get('tests')) and all(proof.get(k)==v for k,v in matches.items()))
    except (OSError,ValueError,TypeError): return False


def read_audio(path):
    with wave.open(str(path),'rb') as wav:
        if wav.getframerate()!=16000 or wav.getnchannels()!=1 or wav.getcomptype()!='NONE':
            raise ValueError('Expected uncompressed 16 kHz mono PCM WAV; resample explicitly first')
        width=wav.getsampwidth(); raw=wav.readframes(wav.getnframes())
    if width==2: return np.frombuffer(raw,dtype='<i2').astype(np.float32)/32768
    if width==3:
        b=np.frombuffer(raw,dtype=np.uint8).reshape(-1,3).astype(np.int32)
        x=b[:,0]|(b[:,1]<<8)|(b[:,2]<<16)
        x=(x ^ 0x800000)-0x800000
        return x.astype(np.float32)/8388608
    if width==4: return np.frombuffer(raw,dtype='<i4').astype(np.float32)/2147483648
    raise ValueError('Expected PCM16, PCM24 or PCM32 WAV')


class Frontend:
    def __init__(self, model_dir):
        constants=np.load(Path(model_dir)/'frontend.npz')
        self.window=np.pad(constants['window'],(56,56))
        self.fb=constants['fb'].reshape(80,257)
    def __call__(self,audio):
        if len(audio)<320: raise ValueError('Audio is too short for reflected STFT')
        audio=np.asarray(audio,dtype=np.float32)
        emphasized=np.concatenate((audio[:1],audio[1:]-np.float32(.97)*audio[:-1]))
        frames=np.lib.stride_tricks.sliding_window_view(np.pad(emphasized,(256,256),mode='reflect'),512)[::160]
        spectrum=np.fft.rfft(frames*self.window,axis=-1).astype(np.complex64)
        power=(spectrum.real*spectrum.real+spectrum.imag*spectrum.imag).T
        features=np.log(self.fb @ power + np.float32(2**-24)).astype(np.float32)
        valid=len(audio)//160+1
        mean=features[:,:valid].mean(1,keepdims=True)
        std=features[:,:valid].std(1,ddof=1,keepdims=True)
        features=(features-mean)/(std+np.float32(1e-5))
        features[:,valid:]=0
        features=np.pad(features,((0,0),(0,(-features.shape[-1])%16)))
        return np.ascontiguousarray(features[None],dtype=np.float32), np.array([valid],dtype=np.int64)


def decode(log_probs, encoded_length, vocabulary):
    blank=len(vocabulary); previous=blank; tokens=[]
    for i in log_probs[:int(encoded_length)].argmax(-1):
        i=int(i)
        if i!=previous and i!=blank: tokens.append(vocabulary[i])
        previous=i
    tokens=[t for t in tokens if t not in {'[PAD]','[UNK]','[CLS]','[SEP]','[MASK]'}]
    text=' '.join(tokens).replace(' ##','').strip()
    # NeMo AutoTokenizer.ids_to_text calls BertTokenizer.convert_tokens_to_string
    # directly; it does not apply HuggingFace decode's punctuation cleanup.
    return text


class Runtime:
    def __init__(self,model_dir=DEFAULT_MODEL,threads=4):
        self.model_dir=Path(model_dir)
        options=ort.SessionOptions(); options.intra_op_num_threads=threads; options.inter_op_num_threads=1
        options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session=ort.InferenceSession(str(self.model_dir/'model.onnx'),options,providers=['CPUExecutionProvider'])
        self.frontend=Frontend(self.model_dir)
        self.vocabulary=(self.model_dir/'vocab.txt').read_text(encoding='utf-8').splitlines()
    def run(self,audio):
        t=time.perf_counter(); features,lengths=self.frontend(audio); f=time.perf_counter()
        logits,encoded=self.session.run(None,{'features':features,'feature_lengths':lengths}); i=time.perf_counter()
        text=decode(logits[0],encoded[0],self.vocabulary); d=time.perf_counter()
        return {'transcript':text,'audio_seconds':len(audio)/16000,'frontend_seconds':f-t,
                'inference_seconds':i-f,'decode_seconds':d-i,'total_seconds':d-t,
                'encoded_length':int(encoded[0]),'hardware_execution':False,'precision':'FP32'}


def main():
    p=argparse.ArgumentParser(); p.add_argument('wav',type=Path)
    p.add_argument('--model-dir',type=Path,default=DEFAULT_MODEL); p.add_argument('--threads',type=int,default=4)
    p.add_argument('--runs',type=int,default=20); p.add_argument('--warmup',type=int,default=3); p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.runs<1 or a.warmup<0: p.error('runs must be positive and warmup nonnegative')
    audio=read_audio(a.wav); t=time.perf_counter(); runtime=Runtime(a.model_dir,a.threads); setup=time.perf_counter()-t
    for _ in range(a.warmup): runtime.run(audio)
    results=[runtime.run(audio) for _ in range(a.runs)]
    report={'model':'nvidia/stt_en_citrinet_256_ls','model_sha256':hashlib.sha256((a.model_dir/'model.onnx').read_bytes()).hexdigest(),
            'audio_sha256':hashlib.sha256(a.wav.read_bytes()).hexdigest(),'threads':a.threads,'initialization_seconds':setup,
            'warmup':a.warmup,'runs':results,'p50_seconds':float(np.percentile([r['total_seconds'] for r in results],50)),
            'p95_seconds':float(np.percentile([r['total_seconds'] for r in results],95)),
            'original_nemo_wrapper_validated':original_validation(a.model_dir),
            'blas_thread_environment':{k:os.environ.get(k) for k in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS']},
            'platform_note':'Results are from the host executing this command; only KV260 measurements satisfy the speedup gate'}
    content=json.dumps(report,indent=2)+'\n'; print(content)
    if a.output: a.output.write_text(content)


if __name__=='__main__': main()
