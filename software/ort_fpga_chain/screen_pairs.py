"""Select up to 32 legal offloads while retaining diagnostic prefix transcripts.

Selection on these diagnostic inputs is not representative accuracy evidence.
Every proposed graph executes the complete original model; no output correction.
"""
import ctypes,json,sys
from pathlib import Path
import numpy as np
import onnx
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
from probe import session
from common import Frontend,decode,read_audio,corpus,sha,write_json
from graph import candidate,one_pair

def main():
    path=ROOT/'research/fused/cpu-int8-cse.onnx';model=onnx.load(path)
    library=Path(__file__).with_name('libort_fpga.so')
    directory=ROOT/'research/export/citrinet-256-ls';front=Frontend(directory)
    vocab=(directory/'vocab.txt').read_text().splitlines();cpu=session(model)
    records=[]
    for folder in ('user-recording','librispeech-mini','user-stress-ac'):
        records+=corpus(ROOT/'research/eval'/folder/'evaluation.jsonl',('evaluation','test'))
    # Evaluate the previously differing inputs first, then every other prefix.
    tests=[]
    for r in records:
        audio=read_audio(r['path'])
        for seconds in (.25,.5,1,2):
            if seconds>len(audio)/16000:continue
            x,n=front(audio[:round(seconds*16000)]);x=np.ascontiguousarray(x[:,:,:int(n[0])])
            feed={'features':x,'feature_lengths':n};logits,length=cpu.run(None,feed)
            tests.append({'id':r['id'],'seconds':seconds,'feed':feed,
                          'text':decode(logits[0],length[0],vocab),'length':length.copy()})
    priority={('user-speech-original',1),('user-ac-quiet-minus20db',1),
              ('user-ac-quiet-minus20db',2),('user-ac-noise-snr20',.5)}
    tests.sort(key=lambda r:(r['id'],r['seconds']) not in priority)
    names={n.name for n in model.graph.node};selected=[];rows=[]
    for block in range(1,12):
        for index in (0,5,10,15,20):
            dw=f'/encoder/encoder.{block}/mconv.{index}/conv/Conv_quant'
            pw=f'/encoder/encoder.{block}/mconv.{index+1}/conv/Conv_quant'
            if dw not in names or pw not in names or len(selected)==32:continue
            try:graph=candidate(model,True,selected+[(dw,pw)])
            except AssertionError:continue
            runner=session(graph,library);mismatch=None
            for test in tests:
                logits,length=runner.run(None,test['feed']);text=decode(logits[0],length[0],vocab)
                if text!=test['text'] or not np.array_equal(length,test['length']):
                    mismatch={'id':test['id'],'seconds':test['seconds'],'cpu':test['text'],'oracle':text};break
            del runner
            accepted=mismatch is None
            if accepted:selected.append((dw,pw))
            rows.append({'depthwise':dw,'pointwise':pw,'accepted':accepted,'first_mismatch':mismatch})
            print('ACCEPT' if accepted else 'KEEP_CPU',len(selected),dw,flush=True)
    report={'complete':len(selected)==32,'model_sha256':sha(path),'library_sha256':sha(library),
            'source_sha256':sha(__file__),'graph_source_sha256':sha(Path(__file__).with_name('graph.py')),
            'scope':'Greedy diagnostic selection, no hardware or representative WER claim',
            'diagnostic_prefixes':len(tests),'selected':[{'depthwise':a,'pointwise':b} for a,b in selected],
            'candidates':rows,'hardware_execution':False,'representative_corpus_qualified':False}
    write_json(ROOT/'reports/fused/shortwide_selection_screen.json',report)
    assert report['complete'],f'Only {len(selected)} prefix-parity pairs found'
    write_json(Path(__file__).with_name('selection.json'),report)
    print('PASS: selected 32 pairs preserving all diagnostic prefix transcripts',flush=True)

if __name__=='__main__':main()
