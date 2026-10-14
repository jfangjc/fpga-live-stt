"""Validate trimmed padding against original CPU and actual FPGA arithmetic."""
import argparse
import ctypes
import json
from pathlib import Path
import sys
import numpy as np
import onnx
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
from probe import candidate, session, stats
from common import Frontend, read_audio, decode, corpus, errors, sha, identity, environment, write_json


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--nodes',nargs='+',required=True)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    model_path=ROOT/'research/fused/cpu-int8-cse.onnx'
    numerical_path=ROOT/'reports/fused/cse_arm_validation.json'
    numerical=json.loads(numerical_path.read_text())
    proof=json.loads(model_path.with_suffix('.json').read_text())
    directory=ROOT/'research/export/citrinet-256-ls'
    assert numerical['complete'] and numerical['all_logits_bit_exact']
    assert sha(model_path)==numerical['cse_model_sha256']==proof['model_sha256']
    assert identity(directory)==proof['source_identity']
    library=ROOT/'software/ort_fpga_bulk/libort_fpga.so'
    lib=ctypes.CDLL(str(library.resolve())); model=onnx.load(str(model_path))
    runners={'cpu':session(model), 'fpga':session(candidate(model,a.nodes,quant=True),library),
             'oracle':session(candidate(model,a.nodes,oracle=True,quant=True),library)}
    frontend=Frontend(directory); vocab=(directory/'vocab.txt').read_text().splitlines()
    records=[]
    for folder in ('user-recording','librispeech-mini','user-stress-ac'):
        records.extend(corpus(ROOT/'research/eval'/folder/'evaluation.jsonl',('evaluation','test')))
    rows=[]; totals={'original_cpu':0,'cpu':0,'fpga':0}; words=0
    for record in records:
        full=read_audio(record['path'])
        for seconds in [None,.25,.5,1]:
            if seconds is not None and seconds>len(full)/16000:continue
            audio=full if seconds is None else full[:round(seconds*16000)]
            x,n=frontend(audio); trimmed=np.ascontiguousarray(x[:,:,:int(n[0])])
            assert np.all(x[:,:,int(n[0]):]==0)
            original=runners['cpu'].run(None,{'features':x,'feature_lengths':n})
            outputs={}; deltas={}
            for name,runner in runners.items():
                before=stats(lib)
                outputs[name]=runner.run(None,{'features':trimmed,'feature_lengths':n})
                delta={k:v-before[k] for k,v in stats(lib).items()}
                assert delta['physical_calls']==(len(a.nodes) if name=='fpga' else 0)
                assert delta['oracle_calls']==(len(a.nodes) if name=='oracle' else 0)
                deltas[name]=delta
            for left,right in zip(outputs['oracle'],outputs['fpga']):np.testing.assert_array_equal(left,right)
            np.testing.assert_array_equal(original[1],outputs['cpu'][1])
            encoded=int(original[1][0]); left=original[0][:,:encoded]; right=outputs['cpu'][0][:,:encoded]
            assert np.all(np.isfinite(right))
            np.testing.assert_allclose(left,right,rtol=1e-5,atol=1e-4)
            texts={'original_cpu':decode(original[0][0],encoded,vocab)}
            for name,result in outputs.items():
                np.testing.assert_array_equal(original[1],result[1])
                texts[name]=decode(result[0][0],encoded,vocab)
            assert texts['original_cpu']==texts['cpu']
            error_counts={}
            if seconds is None:
                for name in totals:
                    error, count=errors(record.get('reference',record.get('text')),texts[name])
                    totals[name]+=error;error_counts[name]=error
                words+=count
            rows.append({'id':record['id'],'context_seconds':seconds,'audio_sha256':record['audio_sha256'],
                         'padded_frames':x.shape[-1],'trimmed_frames':trimmed.shape[-1],
                         'original_trimmed_valid_logits_bit_exact':bool(np.array_equal(left,right)),
                         'max_valid_logit_difference':float(np.max(np.abs(left-right))),
                         'within_tolerance':True,'original_trimmed_cpu_text_exact':True,
                         'physical_oracle_bit_parity':True,'length_exact':True,'texts':texts,
                         'errors':error_counts,'counters':deltas})
        print('PASS',record['id'],flush=True)
    report={'complete':True,'hardware_execution':True,'feature_padding_policy':'trim_to_valid',
            'scope':'Full diagnostic accuracy and short-prefix numerical parity; no live accuracy claim',
            'nodes':a.nodes,'cpu_model_sha256':sha(model_path),'cpu_validation_sha256':sha(numerical_path),
            'library_sha256':sha(library),'driver_sha256':sha(ROOT/'deployment/experimental-bulk/qn_tile.ko'),
            'firmware_sha256':sha(Path('/lib/firmware/xilinx/asr-v3-bulk/asr-v3-bulk.bit.bin')),
            'pl_clock_hz':int(Path('/sys/bus/platform/devices/asr-v3-bulk-clock/set_rate').read_text()),
            'source_sha256':sha(__file__),'errors':totals,'words':words,
            'wer_degradation_percentage_points':100*(totals['fpga']-totals['original_cpu'])/words,
            'representative_corpus_qualified':False,'clips':rows,'environment':environment()}
    assert report['wer_degradation_percentage_points']<=1
    write_json(a.out,report)


if __name__=='__main__':main()
