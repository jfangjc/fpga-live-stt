"""Check the resident API against measured graphs, including zero warm loads."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
sys.path.insert(0,str(ROOT/'software/latency'))
from common import read_audio,sha,write_json
from dma_irq import configure,snapshot
sys.path.insert(0,str(Path(__file__).parent))
from resident import ShortCacheResidentTranscriber


def main():
    before=snapshot();rows=[]
    try:
        audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')
        for seconds,label,core in [(.5,'half',0),(1,'one',3)]:
            configure(core);report=ROOT/f'reports/fused/shortcache_total_{label}.json'
            fpga=ShortCacheResidentTranscriber(report,'fpga');cpu=ShortCacheResidentTranscriber(report,'cpu')
            clip=audio[:round(seconds*16000)]
            fpga.transcribe(clip);cpu.transcribe(clip)
            for _ in range(10):
                a=cpu.transcribe(clip);b=fpga.transcribe(clip)
                assert a['text']==b['text'] and a['encoded_length']==b['encoded_length']
                assert b['fpga_counters']['physical_calls']==32 and b['fpga_counters']['loads']==0 and b['fpga_counters']['ioctls']==32
                rows.append({'context_seconds':seconds,'cpu':a,'fpga':b})
            del fpga,cpu
    finally:
        for irq,value in before.items():(Path('/proc/irq')/irq/'smp_affinity_list').write_text(value['requested'])
        after=snapshot()
        assert {i:v['requested'] for i,v in after.items()}=={i:v['requested'] for i,v in before.items()}
    write_json(ROOT/'reports/fused/shortcache_resident_validation.json',
               {'complete':True,'hardware_execution':True,'timing_acceptance':False,
                'source_sha256':sha(__file__),'resident_source_sha256':sha(Path(__file__).with_name('resident.py')),
                'accepted_resident_source_sha256':sha(ROOT/'software/latency/resident.py'),
                'irq_before':before,'irq_after':after,'calls':rows})
    print('PASS: resident API, transcript/length parity, 32 physical calls and zero warm loads')


if __name__=='__main__':main()
