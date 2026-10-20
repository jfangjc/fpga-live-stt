"""Paired policy screen; selection is separate from latency confirmation."""
import argparse,gc,json,os,random,time
from pathlib import Path
import numpy as np
from tail_benchmark import *

ap=argparse.ArgumentParser();ap.add_argument('--runs',type=int,default=30);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
items=artifacts();timer=AudioTimer(items);audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')
cpu_config={'threads':4,'spin':10,'level':'extended'}
cpu_screen_path=ROOT/'reports/fused/tail_cpu_policy.json'
cpu_screen=json.loads(cpu_screen_path.read_text());assert cpu_screen['complete'] and cpu_screen['all_logits_bit_exact']
assert cpu_screen['model_sha256']==sha(items['model']) and cpu_screen['residual_tail_library_sha256']==sha(items['tail_library'])
cpu_policies={str(c['context_seconds']):c['selected']['policy'] for c in cpu_screen['contexts']}
policies=[{'threads':t,'spin':s,'level':level,'irq_core':irq}
          for t,s,level,irq in ((4,10,'extended',0),(4,10,'extended',3),(4,0,'extended',0),(4,0,'extended',3),
                               (3,10,'extended',0),(3,10,'extended',3),(4,10,'all',0),(4,0,'all',3))]
random.Random(20261012).shuffle(policies)
affinity=os.sched_getaffinity(0);irq=snapshot();rows=[];summaries=[];before=environment()
try:
    os.sched_setaffinity(0,{3})
    cpu_runners={s:make_session(cpu_graph(items,c),c,[items['boundary_library']]) for s,c in cpu_policies.items()}
    reference={}
    oracle=make_session(items['oracle'],cpu_config,[items['boundary_library'],items['library']])
    for seconds in (.5,1,2.5):
        cpu=cpu_runners[str(seconds)]
        clip=np.ascontiguousarray(audio[:round(seconds*16000)])
        result,logits=timer.call(oracle,clip,'oracle');cpu_result,_=timer.call(cpu,clip,'cpu')
        assert result['text']==cpu_result['text'] and result['length']==cpu_result['length']
        reference[seconds]=(result,logits)
    del oracle;gc.collect()
    for index,config in enumerate(policies):
        configure(config['irq_core'])
        fpga=make_session(items['fpga'],config,[items['boundary_library'],items['library']])
        rng=random.Random(20261012+index)
        for seconds in (.5,1,2.5):
            cpu=cpu_runners[str(seconds)]
            clip=np.ascontiguousarray(audio[:round(seconds*16000)])
            physical,actual=timer.call(fpga,clip,'fpga');expected,logits=reference[seconds]
            np.testing.assert_array_equal(actual,logits);assert physical['text']==expected['text'] and physical['length']==expected['length']
            for _ in range(5):timer.call(cpu,clip,'cpu');timer.call(fpga,clip,'fpga')
            samples=[]
            for iteration in range(a.runs):
                order=['cpu','fpga'];rng.shuffle(order);results={}
                for kind in order:
                    time.sleep(.003);results[kind],_=timer.call(cpu if kind=='cpu' else fpga,clip,kind)
                assert results['fpga']['counters']['loads']==0 and results['fpga']['counters']['ioctls']==10
                assert results['cpu']['text']==results['fpga']['text'] and results['cpu']['length']==results['fpga']['length']
                row={'policy_index':index,'context_seconds':seconds,'index':iteration,'order':order,'results':results}
                samples.append(row);rows.append(row)
            summary={'policy_index':index,'policy':config,'context_seconds':seconds}
            for kind in ('cpu','fpga'):
                values=[r['results'][kind]['seconds'] for r in samples]
                summary[kind+'_p50']=float(np.median(values));summary[kind+'_p95']=float(np.percentile(values,95))
            summary['latency_reduction_percent']=100*(1-summary['fpga_p50']/summary['cpu_p50'])
            summaries.append(summary);print(json.dumps(summary),flush=True)
        del fpga;gc.collect()
    selected=[]
    for seconds in (.5,1,2.5):
        candidates=[s for s in summaries if s['context_seconds']==seconds]
        selected.append(min(candidates,key=lambda s:s['fpga_p50']))
    write_json(a.out,bindings(items)|{'complete':True,'timing_acceptance':False,'scope':'Policy screen; independent paired confirmation required',
                                    'cpu_policies':cpu_policies,'policies':policies,'selected':selected,'summaries':summaries,'runs':rows,
                                    'cpu_policy_screen_sha256':sha(cpu_screen_path),'source_sha256':sha(__file__),
                                    'environment_before':before,'environment_after':environment()})
finally:
    os.sched_setaffinity(0,affinity)
    for number,value in irq.items():(Path('/proc/irq')/number/'smp_affinity_list').write_text(value['requested'])
