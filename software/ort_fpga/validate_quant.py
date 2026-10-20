"""Accuracy regression for fused FPGA arithmetic before physical deployment."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import onnx
from probe import ROOT,candidate,session
sys.path.insert(0,str(ROOT/'software/fused'))
from common import Frontend,read_audio,decode,corpus,errors,sha,write_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--nodes',nargs='+',required=True)
    p.add_argument('--model',type=Path,default=ROOT/'research/fused/cpu-int8.onnx')
    p.add_argument('--library',type=Path,default=Path(__file__).with_name('libort_fpga.so'))
    p.add_argument('--manifests',type=Path,nargs='+',required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    model=onnx.load(str(args.model));baseline=session(model)
    oracle=session(candidate(model,args.nodes,True,True),args.library)
    directory=ROOT/'research/export/citrinet-256-ls'
    frontend=Frontend(directory);vocab=(directory/'vocab.txt').read_text().splitlines()
    rows=[]
    for manifest in args.manifests:
        for r in corpus(manifest,('evaluation','test')):
            x,length=frontend(read_audio(r['path']));feed={'features':x,'feature_lengths':length}
            a,la=baseline.run(None,feed);b,lb=oracle.run(None,feed)
            np.testing.assert_array_equal(la,lb)
            if a.shape!=b.shape or not np.all(np.isfinite(b)):raise ValueError('Invalid oracle output')
            at=decode(a[0],la[0],vocab);bt=decode(b[0],lb[0],vocab)
            reference=r.get('reference',r.get('text'))
            ae,words=errors(reference,at);be,_=errors(reference,bt)
            rows.append({'id':r['id'],'cpu_text':at,'oracle_text':bt,
                         'reference':reference,'cpu_errors':ae,'reference_words':words,
                         'oracle_errors':be,
                         'max_logit_difference':float(np.max(np.abs(a-b))),
                         'max_valid_logit_difference':float(np.max(np.abs(a[:,:int(la[0])]-b[:,:int(lb[0])]))),
                         'audio_sha256':r['audio_sha256'],'manifest':str(manifest)})
            print(r['id'],'same text',at==bt,flush=True)
    write_json(args.out,{'hardware_execution':False,'nodes':args.nodes,
                        'model_sha256':sha(args.model),'library_sha256':sha(args.library),
                        'all_transcripts_identical':all(r['cpu_text']==r['oracle_text'] for r in rows),
                        'clips':rows,'representative_accuracy_claimed':False})


if __name__=='__main__':main()
