"""Recorded-input accuracy and paired frontend-only screening, on the board."""
import argparse
import json
from pathlib import Path
import random
import time
import numpy as np
import onnxruntime as ort
from frontend_sparse import ROOT, SparseFrontend, Frontend
import sys
sys.path.insert(0, str(ROOT/'software/fused'))
from common import corpus, decode, errors, read_audio, sha, identity, environment, write_json

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--runs',type=int,default=50)
    a=ap.parse_args()
    if a.runs < 20: ap.error('At least 20 paired frontend timings required')
    directory=ROOT/'research/export/citrinet-256-ls'
    model=ROOT/'research/fused/cpu-int8.onnx'
    proof=json.loads(model.with_suffix('.json').read_text())
    assert sha(model)==proof['model_sha256'] and identity(directory)==proof['source_identity']
    frontends={'original':Frontend(directory),'sparse':SparseFrontend(directory)}
    opt=ort.SessionOptions();opt.intra_op_num_threads=4;opt.inter_op_num_threads=1
    opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
    opt.add_session_config_entry('session.intra_op.allow_spinning','0')
    opt.add_session_config_entry('session.inter_op.allow_spinning','0')
    runner=ort.InferenceSession(str(model),opt,providers=['CPUExecutionProvider'])
    vocab=(directory/'vocab.txt').read_text().splitlines()
    records=[]
    for folder in ('user-recording','librispeech-mini','user-stress-ac'):
        records.extend(corpus(ROOT/'research/eval'/folder/'evaluation.jsonl',('evaluation','test')))
    assert not set(proof['calibration_audio_sha256']) & {r['audio_sha256'] for r in records}
    accuracy=[];total_errors={'original':0,'sparse':0};words=0
    for record in records:
        audio=read_audio(record['path']);results={};features={};lengths={};logits={}
        for name, frontend in frontends.items():
            x,n=frontend(audio);features[name]=x;lengths[name]=n
            y,enc=runner.run(None,{'features':x,'feature_lengths':n});logits[name]=y
            text=decode(y[0],enc[0],vocab)
            count,word_count=errors(record.get('reference',record.get('text')),text)
            total_errors[name]+=count
            results[name]={'text':text,'errors':count,'encoded_length':int(enc[0])}
        words+=word_count
        np.testing.assert_array_equal(lengths['original'],lengths['sparse'])
        np.testing.assert_allclose(features['original'],features['sparse'],atol=1e-5,rtol=1e-5)
        assert results['original']['encoded_length']==results['sparse']['encoded_length']
        accuracy.append({'id':record['id'],'audio_sha256':record['audio_sha256'],
                         'feature_max_abs_difference':float(np.max(np.abs(features['original']-features['sparse']))),
                         'logit_max_abs_difference':float(np.max(np.abs(logits['original']-logits['sparse']))),
                         'features_bit_exact':bool(np.array_equal(features['original'],features['sparse'])),
                         'logits_bit_exact':bool(np.array_equal(logits['original'],logits['sparse'])),
                         'results':results})
    rng=random.Random(11102026);timings=[]
    full=read_audio(ROOT/'research/eval/user-recording/speech.wav')
    before_env=environment()
    for seconds in (.5,1,2,4,8,10):
        audio=full[:round(seconds*16000)]
        for _ in range(3):
            for frontend in frontends.values():frontend(audio)
        pairs=[]
        for i in range(a.runs):
            order=list(frontends);rng.shuffle(order);row={}
            for name in order:
                start=time.perf_counter();frontends[name](audio);row[name]=time.perf_counter()-start
            pairs.append(row)
        original=np.array([v['original'] for v in pairs]);sparse=np.array([v['sparse'] for v in pairs])
        indices=np.random.default_rng(111026).integers(0,a.runs,(10000,a.runs))
        timings.append({'context_seconds':seconds,'original_p50':float(np.median(original)),
                        'sparse_p50':float(np.median(sparse)),
                        'mean_saving_95ci_seconds':np.percentile((original-sparse)[indices].mean(1),[2.5,97.5]).tolist(),
                        'paired_runs':pairs})
    report={'complete':True,'scope':'Experimental frontend-only timings and CPU graph diagnostic accuracy; no physical FPGA speed claim',
            'hardware_execution':False,'runs':a.runs,'cpu_model_sha256':sha(model),
            'source_sha256':{p.name:sha(p) for p in [Path(__file__),Path(__file__).with_name('frontend_sparse.py'),ROOT/'software/model-tools/citrinet_cpu.py']},
            'filterbank_nonzero':int(np.count_nonzero(frontends['original'].fb)),
            'filterbank_coefficients':int(frontends['original'].fb.size),
            'errors':total_errors,'words':words,
            'wer_degradation_percentage_points':100*(total_errors['sparse']-total_errors['original'])/words,
            'representative_corpus_qualified':False,'accuracy':accuracy,'frontend_timings':timings,
            'environment_before':before_env,'environment_after':environment()}
    write_json(a.out,report)
    assert report['wer_degradation_percentage_points']<=1
    print(json.dumps({'errors':total_errors,'words':words,'frontend_timings':[{k:v for k,v in r.items() if k!='paired_runs'} for r in timings]}),flush=True)

if __name__=='__main__':main()
