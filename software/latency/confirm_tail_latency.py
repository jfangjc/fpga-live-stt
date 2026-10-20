"""Independent paired warm measurements against the fastest screened CPU."""
import argparse,gc,json,os,random,time
from pathlib import Path
import numpy as np
from tail_benchmark import *

ap=argparse.ArgumentParser();ap.add_argument('--policy',type=Path,required=True);ap.add_argument('--runs',type=int,default=300)
ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();assert a.runs>=100
screen=json.loads(a.policy.read_text());assert screen['complete'] and not screen['timing_acceptance']
items=artifacts();bound=bindings(items)
for key in ('firmware_sha256','library_sha256','boundary_library_sha256','cpu_model_sha256','residual_tail_library_sha256'):assert screen[key]==bound[key]
timer=AudioTimer(items);audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')
affinity=os.sched_getaffinity(0);irq=snapshot();before=environment();contexts=[]
try:
    os.sched_setaffinity(0,{3})
    cpu=None
    for selected in screen['selected']:
        seconds=selected['context_seconds'];config=selected['policy'];configure(config['irq_core'])
        cpu_policy=screen['cpu_policies'][str(seconds)]
        cpu=make_session(cpu_graph(items,cpu_policy),cpu_policy,[items['boundary_library']])
        fpga=make_session(items['fpga'],config,[items['boundary_library'],items['library']])
        oracle=make_session(items['oracle'],cpu_policy,[items['boundary_library'],items['library']])
        clip=np.ascontiguousarray(audio[:round(seconds*16000)])
        cold,actual=timer.call(fpga,clip,'fpga');expected,logits=timer.call(oracle,clip,'oracle');cpu_first,_=timer.call(cpu,clip,'cpu')
        np.testing.assert_array_equal(actual,logits)
        assert cold['text']==expected['text']==cpu_first['text'] and cold['length']==cpu_first['length']
        del oracle;gc.collect()
        for _ in range(10):timer.call(cpu,clip,'cpu');timer.call(fpga,clip,'fpga')
        rng=random.Random(202610120+round(seconds*100));rows=[]
        for iteration in range(a.runs):
            order=['cpu','fpga'];rng.shuffle(order);results={}
            for kind in order:
                time.sleep(.003);results[kind],_=timer.call(cpu if kind=='cpu' else fpga,clip,kind)
            assert results['fpga']['counters']['loads']==0 and results['fpga']['counters']['ioctls']==10
            assert results['cpu']['text']==results['fpga']['text']==cold['text'] and results['cpu']['length']==results['fpga']['length']
            rows.append({'index':iteration,'order':order,'results':results})
        samples={kind:np.array([r['results'][kind]['seconds'] for r in rows]) for kind in ('cpu','fpga')}
        summary={'context_seconds':seconds,'fpga_policy':config,'cpu_policy':cpu_policy,
                 'physical_oracle_bit_exact':True,'all_text_and_lengths_equal':True,'cold_fpga':cold,'runs':rows}
        for kind in ('cpu','fpga'):
            summary[kind+'_p50']=float(np.median(samples[kind]));summary[kind+'_p95']=float(np.percentile(samples[kind],95))
        summary['latency_reduction_percent']=100*(1-summary['fpga_p50']/summary['cpu_p50'])
        bootstrap=np.random.default_rng(20261012).integers(0,a.runs,(10000,a.runs))
        reductions=100*(1-np.median(samples['fpga'][bootstrap],axis=1)/np.median(samples['cpu'][bootstrap],axis=1))
        summary['paired_bootstrap_95ci_percent']=np.percentile(reductions,[2.5,97.5]).tolist()
        summary['meets_20_percent']=bool(summary['latency_reduction_percent']>=20 and summary['fpga_p95']<summary['cpu_p95'])
        contexts.append(summary);print(json.dumps({k:v for k,v in summary.items() if k!='runs'}),flush=True)
        del fpga;gc.collect()
    write_json(a.out,bound|{'complete':True,'timing_acceptance':all(c['meets_20_percent'] for c in contexts),
                          'scope':'Warm full audio path including frontend, transfer, synchronization, model and decode; diagnostic prefixes',
                          'runs_per_context':a.runs,'contexts':contexts,'policy_screen_sha256':sha(a.policy),
                          'source_sha256':sha(__file__),'environment_before':before,'environment_after':environment()})
finally:
    os.sched_setaffinity(0,affinity)
    for number,value in irq.items():(Path('/proc/irq')/number/'smp_affinity_list').write_text(value['requested'])
