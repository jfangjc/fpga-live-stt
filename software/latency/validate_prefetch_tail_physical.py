"""Full-model physical chain/oracle/CPU diagnostic prefix parity."""
import argparse,json,os
from pathlib import Path
import numpy as np
import onnx
from prefetch_tail_benchmark import *
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
items=artifacts();timer=AudioTimer(items);config={'threads':4,'spin':10,'level':'extended'}
affinity=os.sched_getaffinity(0);irq=snapshot();rows=[]
try:
    os.sched_setaffinity(0,{3});configure(3)
    runners={kind:make_session(items[kind],config,[items['boundary_library']]+([] if kind=='cpu' else [items['library']]))
             for kind in ('cpu','fpga','oracle')}
    original_cpu=make_session(onnx.load(items['model']),config)
    records=[]
    for folder in ('user-recording','librispeech-mini','user-stress-ac'):
        records+=corpus(ROOT/'research/eval'/folder/'evaluation.jsonl',('evaluation','test'))
    for record in records:
        audio=read_audio(record['path'])
        for seconds in (.25,.5,1,2):
            if seconds>len(audio)/16000:continue
            clip=np.ascontiguousarray(audio[:round(seconds*16000)])
            physical,actual=timer.call(runners['fpga'],clip,'fpga')
            oracle,expected=timer.call(runners['oracle'],clip,'oracle')
            cpu,cpu_logits=timer.call(runners['cpu'],clip,'cpu')
            original,original_logits=timer.call(original_cpu,clip,'cpu')
            np.testing.assert_array_equal(cpu_logits,original_logits)
            assert cpu['text']==original['text'] and cpu['length']==original['length']
            np.testing.assert_array_equal(actual,expected)
            assert physical['text']==oracle['text']==cpu['text'] and physical['length']==cpu['length']
            assert physical['counters']['ioctls']==10+(64 if not rows else 0)
            row={'id':record['id'],'seconds':seconds,'physical_oracle_bit_exact':True,'cpu_text_exact':True,
                 'cpu_boundary_logits_bit_exact':True,'length_exact':True,'text':physical['text'],'physical_counters':physical['counters']}
            rows.append(row);print(json.dumps(row),flush=True)
finally:
    os.sched_setaffinity(0,affinity)
    for number,value in irq.items():(Path('/proc/irq')/number/'smp_affinity_list').write_text(value['requested'])
a.out.parent.mkdir(parents=True,exist_ok=True);onnx.save(items['fpga'],a.out.with_suffix('.onnx'))
write_json(a.out,bindings(items)|{'complete':True,'scope':'Diagnostic prefixes; no representative WER claim',
                                'clips':rows,'groups':items['groups'],'source_sha256':sha(__file__),
                                'graph_sha256':sha(a.out.with_suffix('.onnx'))})
