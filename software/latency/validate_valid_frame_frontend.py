"""Exact model-input contract and frontend-only paired timings; no FPGA claim."""
import argparse
import hashlib
import json
import random
import sys
import time
from pathlib import Path
import numpy as np
from frontend_valid_frames import ValidFrameFrontend
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/model-tools'))
from citrinet_cpu import Frontend, read_audio
ap = argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
directory=ROOT/'research/export/citrinet-256-ls'
original=Frontend(directory);candidate=ValidFrameFrontend(directory)
def call(frontend,audio):
    x,n=frontend(audio)
    return np.ascontiguousarray(x[:,:,:int(n[0])]),n
cases=[]
for folder in ('user-recording','librispeech-mini','user-stress-ac'):
    for line in (ROOT/'research/eval'/folder/'evaluation.jsonl').read_text().splitlines():
        record=json.loads(line);audio=read_audio(ROOT/'research/eval'/folder/record['audio'])
        for seconds in (.25,.5,1,2,2.5):
            if round(seconds*16000)>len(audio):continue
            clip=np.ascontiguousarray(audio[:round(seconds*16000)])
            left,n=call(original,clip);right,m=call(candidate,clip)
            np.testing.assert_array_equal(left.view(np.uint32),right.view(np.uint32));np.testing.assert_array_equal(n,m)
            cases.append({'id':record['id'],'seconds':seconds,'model_input_bit_exact':True})
rng=np.random.default_rng(20261015)
for size in (320,321,479,480,481,7999,8000,8001,15999,16000,16001,39999,40000):
    for quiet in (False,True):
        clip=np.zeros(size,np.float32) if quiet else rng.uniform(-1,1,size).astype(np.float32)
        left,n=call(original,clip);right,m=call(candidate,clip)
        np.testing.assert_array_equal(left.view(np.uint32),right.view(np.uint32));np.testing.assert_array_equal(n,m)
        cases.append({'synthetic_samples':size,'silence':quiet,'model_input_bit_exact':True})
audio=read_audio(ROOT/'research/eval/user-recording/speech.wav');timings=[]
for seconds in (.5,1,2.5):
    clip=np.ascontiguousarray(audio[:round(seconds*16000)]);rows=[]
    for _ in range(10):call(original,clip);call(candidate,clip)
    order_rng=random.Random(20261015+int(seconds*10))
    for i in range(100):
        order=['original','valid_frames'];order_rng.shuffle(order);row={}
        for name in order:
            start=time.perf_counter();call(original if name=='original' else candidate,clip)
            row[name]=time.perf_counter()-start
        rows.append(row)
    timings.append({'context_seconds':seconds,'original_p50':float(np.median([r['original'] for r in rows])),
                    'valid_frames_p50':float(np.median([r['valid_frames'] for r in rows])),'paired_runs':rows})
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
report={'complete':True,'hardware_execution':False,'all_model_inputs_bit_exact':True,'cases':cases,
        'frontend_only_timings':timings,'source_sha256':sha(Path(__file__)),
        'candidate_sha256':sha(ROOT/'software/latency/frontend_valid_frames.py'),
        'pinned_frontend_sha256':sha(ROOT/'software/model-tools/citrinet_cpu.py'),
        'scope':'Private valid-frame input contract only; no model/FPGA speed acceptance'}
a.out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('cases','frontend_only_timings')}))
print(json.dumps([{k:v for k,v in t.items() if k!='paired_runs'} for t in timings]))
