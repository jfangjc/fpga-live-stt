"""Validate public short-input profiles, residency and affinity restoration."""
import json
import os
from pathlib import Path
import time
import numpy as np
from resident import ResidentTranscriber, ROOT, read_audio, sha
from dma_irq import configure, snapshot


def main():
    full=read_audio(ROOT/'research/eval/user-recording/speech.wav')
    affinity=os.sched_getaffinity(0); rows=[]
    profiles=[('half', 'short_half_second_deployment.json', [.25,.5]),
              ('one','short_one_second_irq3_deployment.json',[1])]
    for label,name,contexts in profiles:
        proof=ROOT/'reports/fused'/name
        configure(0 if label=='half' else 3)
        cpu=ResidentTranscriber(proof,'cpu'); fpga=ResidentTranscriber(proof,'fpga')
        assert os.sched_getaffinity(0)==affinity
        for seconds in contexts:
            audio=np.ascontiguousarray(full[:round(seconds*16000)])
            for _ in range(3):fpga.transcribe(audio)
            for i in range(3):
                time.sleep(.003); left=cpu.transcribe(audio)
                time.sleep(.003); right=fpga.transcribe(audio)
                assert left['text']==right['text'] and left['encoded_length']==right['encoded_length']
                assert os.sched_getaffinity(0)==affinity
                counter=right['fpga_counters']
                assert counter['physical_calls']==len(fpga.nodes) and counter['oracle_calls']==0
                if label=='half':assert counter['loads']==0 and counter['ioctls']==1
                rows.append({'profile':label,'context_seconds':seconds,'repeat':i,'cpu':left,'fpga':right})
        invalid=np.array([np.nan]*8000,np.float32)
        try:fpga.transcribe(invalid)
        except ValueError:pass
        else:raise AssertionError('Nonfinite audio was accepted')
        assert os.sched_getaffinity(0)==affinity
        del cpu,fpga
    out=ROOT/'reports/fused/short_resident_smoke.json'
    report={'complete':True,'scope':'API integration checks; not latency acceptance',
            'hardware_execution':True,'caller_affinity_restored':True,'nonfinite_input_rejected':True,
            'resident_source_sha256':sha(Path(__file__).with_name('resident.py')),
            'smoke_source_sha256':sha(__file__),
            'profile_sha256':{label:sha(ROOT/'reports/fused'/name) for label,name,_ in profiles},'calls':rows}
    out.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS short resident profiles',flush=True)


if __name__=='__main__':
    previous=snapshot()
    try:main()
    finally:
        for irq,value in previous.items():
            (Path('/proc/irq')/irq/'smp_affinity_list').write_text(value['requested'])
        assert snapshot()==previous
