"""Bind optimized graph accuracy to real FPGA output and integer emulation."""
import argparse
import ctypes
import json
from pathlib import Path
import sys
import numpy as np
import onnx
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
from probe import candidate,session,stats
from common import Frontend,read_audio,decode,corpus,errors,sha,identity,environment,write_json

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--nodes',nargs='+',required=True)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    model_path=ROOT/'research/fused/cpu-int8-cse.onnx'
    proof=json.loads(model_path.with_suffix('.json').read_text())
    validation_path=ROOT/'reports/fused/cse_arm_validation.json'
    validation=json.loads(validation_path.read_text())
    assert validation['complete'] and validation['all_logits_bit_exact']
    assert sha(model_path)==proof['model_sha256']==validation['cse_model_sha256']
    directory=ROOT/'research/export/citrinet-256-ls'
    assert identity(directory)==proof['source_identity']
    library=ROOT/'software/ort_fpga_bulk/libort_fpga.so'
    lib=ctypes.CDLL(str(library.resolve()))
    model=onnx.load(str(model_path));runners={}
    for name,graph in [('cpu',model),('fpga',candidate(model,a.nodes,quant=True)),
                       ('oracle',candidate(model,a.nodes,oracle=True,quant=True))]:
        runners[name]=session(graph,None if name=='cpu' else library)
    frontend=Frontend(directory);vocab=(directory/'vocab.txt').read_text().splitlines()
    records=[]
    for folder in ('user-recording','librispeech-mini','user-stress-ac'):
        records.extend(corpus(ROOT/'research/eval'/folder/'evaluation.jsonl',('evaluation','test')))
    assert not set(proof['calibration_audio_sha256']) & {r['audio_sha256'] for r in records}
    rows=[];counts={'cpu':0,'fpga':0};words=0
    for record in records:
        x,n=frontend(read_audio(record['path']));feed={'features':x,'feature_lengths':n}
        results={};outputs={};lengths={};deltas={}
        for name in ('cpu','oracle','fpga'):
            before=stats(lib)
            y,enc=runners[name].run(None,feed)
            after=stats(lib);delta={k:after[k]-before[k] for k in after}
            assert delta['physical_calls']==(len(a.nodes) if name=='fpga' else 0)
            assert delta['oracle_calls']==(len(a.nodes) if name=='oracle' else 0)
            assert np.all(np.isfinite(y))
            outputs[name]=y;lengths[name]=enc;deltas[name]=delta
            text=decode(y[0],enc[0],vocab)
            error,word_count=errors(record.get('reference',record.get('text')),text)
            results[name]={'text':text,'errors':error,'encoded_length':int(enc[0])}
            if name in counts: counts[name]+=error
        words+=word_count
        np.testing.assert_array_equal(outputs['oracle'],outputs['fpga'])
        np.testing.assert_array_equal(lengths['oracle'],lengths['fpga'])
        np.testing.assert_array_equal(lengths['cpu'],lengths['fpga'])
        rows.append({'id':record['id'],'audio_sha256':record['audio_sha256'],
                     'physical_oracle_bit_parity':True,'results':results,'counters':deltas})
        print('PASS physical',record['id'],flush=True)
    report={'complete':True,'hardware_execution':True,'scope':'Physical integer parity and diagnostic accuracy; not timing acceptance',
            'nodes':a.nodes,'cpu_model_sha256':sha(model_path),'cpu_validation_sha256':sha(validation_path),
            'library_sha256':sha(library),'driver_sha256':sha(ROOT/'deployment/experimental-bulk/qn_tile.ko'),
            'firmware_sha256':sha(Path('/lib/firmware/xilinx/asr-v3-bulk/asr-v3-bulk.bit.bin')),
            'pl_clock_hz':int(Path('/sys/bus/platform/devices/asr-v3-bulk-clock/set_rate').read_text()),
            'source_sha256':sha(Path(__file__)),'errors':counts,'words':words,
            'wer_degradation_percentage_points':100*(counts['fpga']-counts['cpu'])/words,
            'representative_corpus_qualified':False,'clips':rows,'environment':environment()}
    write_json(a.out,report)
    assert report['wer_degradation_percentage_points']<=1

if __name__=='__main__':main()
