import hashlib, json, time
from pathlib import Path
import numpy as np
import soundfile as sf
from moonshine.matrix import BulkDevice
from moonshine.model import load
from moonshine.ort_decoder import Runtime
from moonshine.streaming import Stream
audio, _ = sf.read('/home/ubuntu/kv260-asr-mvp-20261015/reports/test-inputs/speech_25.wav', dtype='float32')
previous=json.loads(Path('reports/local/tiny-ort-stress.json').read_text())
short=json.loads(Path('reports/local/tiny-ort-v1/oracle-2.json').read_text())
device=BulkDevice('build/native/libqnc_moonshine.so')
results={}
try:
    model, processor, meta=load('tiny', 'fpga', device=device, threads=2)
    runtime=Runtime('build/tiny-decoder-v2', meta, threads=4)
    for count in (1, 2, 4):
        samples=np.tile(audio,count)
        runs=[]
        for run in range(-1,3):
            stream=Stream(model,processor,decoder_runtime=runtime)
            start=time.perf_counter(); events=[]
            for off in range(0,len(samples),8000): events.append(stream.push(samples[off:off+8000]))
            events.append(stream.finish())
            runs.append({'run':run,'seconds':time.perf_counter()-start,'profile':stream.profile,'events':events})
        expected=short['runs'][0]['events'] if count==1 else previous['cases']['repeat-%ds'%(count*2.5)]['oracle']['runs'][0]['events']
        parity=all([e['tokens'] for e in r['events']]==[e['tokens'] for e in expected] for r in runs)
        results[str(count*2.5)]={'audio_seconds':len(samples)/16000,'oracle_tokens_equal':parity,'runs':runs}
        print(count*2.5,[r['seconds'] for r in runs],parity,flush=True)
    report={'metadata':meta,'decoder_runtime':runtime.metadata,'cases':results,'physical':device.stats()}
    Path('reports/local/tiny-ort-four.json').write_text(json.dumps(report,indent=2)+'\n')
finally: device.close()
