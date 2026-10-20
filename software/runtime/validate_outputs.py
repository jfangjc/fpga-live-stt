"""Separate physical-vs-INT8 implementation parity from FP32 drift and WER."""
import argparse
from contextlib import ExitStack
import json
import time
from pathlib import Path
import numpy as np
from citrinet_adapter import Runner,read_audio,decode,digest

def implementation_parity(expected,actual,expected_text,actual_text,atol=1e-4,rtol=1e-5):
    """Both outputs are [log_probs BTV, encoded_lengths B], no broadcasting."""
    a,alen=map(np.asarray,expected);b,blen=map(np.asarray,actual)
    shapes_equal=a.shape==b.shape and alen.shape==blen.shape
    finite=bool(np.all(np.isfinite(a)) and np.all(np.isfinite(b)))
    lengths_equal=bool(shapes_equal and np.array_equal(alen,blen))
    lengths_valid=bool(a.ndim==3 and b.ndim==3 and alen.ndim==1 and blen.ndim==1 and
        len(alen)==a.shape[0] and len(blen)==b.shape[0] and
        np.issubdtype(alen.dtype,np.integer) and np.issubdtype(blen.dtype,np.integer) and
        np.all((alen>0)&(alen<=a.shape[1])) and np.all((blen>0)&(blen<=b.shape[1])))
    logits_close=bool(shapes_equal and finite and np.allclose(b,a,atol=atol,rtol=rtol))
    transcripts_equal=expected_text==actual_text
    passed=bool(shapes_equal and finite and lengths_equal and lengths_valid and logits_close and transcripts_equal)
    return {'passed':passed,'shapes_equal':shapes_equal,'finite':finite,'encoded_lengths_equal':lengths_equal,
            'encoded_lengths_valid':lengths_valid,'logits_within_tolerance':logits_close,
            'transcripts_match':transcripts_equal,'absolute_tolerance':atol,'relative_tolerance':rtol,
            'max_abs_logprob_error':float(np.max(np.abs(a-b))) if shapes_equal and finite and a.size else None}

def positive_dma(stats):
    return bool(stats and all(isinstance(stats.get(k),(int,float)) and stats[k]>0
               for k in ('loads','runs','ioctls','tx_bytes','rx_bytes')))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('wav',type=Path)
    p.add_argument('--mode',choices=['emulate','fpga'],default='emulate');p.add_argument('--threads',type=int,default=4)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    with ExitStack() as cleanup:
        cpu=Runner('cpu',args.threads);cleanup.callback(cpu.close)
        hybrid=Runner(args.mode,args.threads);cleanup.callback(hybrid.close)
        emulator=None
        if args.mode=='fpga':
            emulator=Runner('emulate',args.threads);cleanup.callback(emulator.close)
        audio=read_audio(args.wav);features,lengths=cpu.frontend(audio)
        feeds={'features':features,'feature_lengths':lengths}
        start=time.perf_counter();a=cpu.graph.run(None,feeds);cpu_seconds=time.perf_counter()-start
        start=time.perf_counter();b=hybrid.graph.run(feeds);hybrid_seconds=time.perf_counter()-start
        if a[0].shape!=b[0].shape or not np.all(np.isfinite(b[0])): raise ValueError('Nonfinite/mismatched hybrid output')
        text_a=decode(a[0][0],a[1][0],cpu.vocab);text_b=decode(b[0][0],b[1][0],cpu.vocab)
        stats=hybrid.device.stats() if hybrid.device else None
        parity=None
        if emulator:
            expected=emulator.graph.run(feeds)
            text_expected=decode(expected[0][0],expected[1][0],emulator.vocab)
            parity=implementation_parity(expected,b,text_expected,text_b)
            parity['numerical_int8_transcript']=text_expected
            parity['positive_physical_dma_work']=positive_dma(stats)
            parity['passed']=parity['passed'] and parity['positive_physical_dma_work']
        report={'hardware_execution':args.mode=='fpga','mode':args.mode,'metadata':hybrid.metadata(),
            'audio_sha256':digest(args.wav),'audio_seconds':len(audio)/16000,'encoded_lengths':b[1].tolist(),
            'cpu_transcript':text_a,'hybrid_transcript':text_b,'transcripts_match':text_a==text_b,
            'cpu_encoded_lengths_equal':bool(np.array_equal(a[1],b[1])),
            'max_abs_logprob_error':float(np.max(np.abs(a[0]-b[0]))),
            'mean_abs_logprob_error':float(np.mean(np.abs(a[0]-b[0]))),
            'valid_frame_argmax_agreement':float(np.mean(a[0][0,:a[1][0]].argmax(-1)==b[0][0,:b[1][0]].argmax(-1))),
            'cpu_graph_seconds':cpu_seconds,'hybrid_graph_seconds':hybrid_seconds,
            'profile_seconds':{kind:sum(x['seconds'] for x in hybrid.graph.last_profile if x['kind']==kind) for kind in ('cpu','fpga')},
            'dma':stats,'physical_vs_numerical_int8_implementation_parity':parity,
            'limits':['FP32 CPU differences quantify quantization drift, without an implementation-parity threshold',
                      'Graph times exclude frontend/decoding and are not end-to-end speedup','One waveform is not a WER corpus']}
        args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
        if parity is not None and not parity['passed']: raise SystemExit(2)

if __name__=='__main__': main()
