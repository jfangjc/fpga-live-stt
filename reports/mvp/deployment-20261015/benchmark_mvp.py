"""Reproduce paired CPU/physical-FPGA measurements without changing MVP sources."""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--worker', action='store_true')
parser.add_argument('--runs', type=int, default=300)
args = parser.parse_args()
root = args.root.resolve()
sys.path[:0] = [str(root/'scripts'), str(root/'software/mvp')]
out = root/'reports/comparison'
out.mkdir(exist_ok=True, parents=True)


def save(name, value):
    (out/name).write_text(json.dumps(value, indent=2)+'\n')


def environment():
    paths = list(Path('/sys/class/hwmon').glob('hwmon*/temp*_input'))
    paths += list(Path('/sys/devices/system/cpu/cpufreq').glob('policy*/scaling_*'))
    values = {}
    for p in paths:
        try:
            values[str(p)] = p.read_text().strip()
        except OSError:
            pass
    return {'kernel': platform.release(), 'python': platform.python_version(),
            'sysfs': values, 'loadavg': Path('/proc/loadavg').read_text().strip()}


if not args.worker:
    from board import preflight, state, BRANCH, driver
    from setup_board import activate_bulk
    from run_board import restore_irqs
    preflight(root)
    before = state(root)
    save('before.json', before)
    def terminate(signum, frame):
        raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM, terminate)
    try:
        subprocess.run(['rmmod','qn_tile'],check=True)
        subprocess.run(['xmutil','unloadapp'],check=True)
        subprocess.run(['xmutil','loadapp',BRANCH],check=True)
        (Path('/sys/bus/platform/devices')/(BRANCH+'-clock')/'set_rate').write_text('166666666')
        subprocess.run(['insmod',str(driver(root,True))],check=True)
        save('active.json',state(root,True))
        subprocess.run([sys.executable,__file__,'--root',str(root),'--worker','--runs',str(args.runs)],check=True)
    finally:
        activate_bulk(root)
        restore_irqs(before['irq'])
        after = state(root)
        if after['driver_sha256'] != before['driver_sha256']:
            raise RuntimeError('Restored driver differs')
        save('restored.json',after)
        print('PASS: benchmark bulk firmware, clock, module and IRQ rollback',flush=True)
    sys.exit(0)

import numpy as np
import onnxruntime as ort
from runtime import graphs, session, AudioTimer
from frontend import read_audio
from board import configure_irqs, state

save('environment-before.json',environment())
policies = json.loads((root/'config/policies.json').read_text())
start = time.perf_counter()
cpu_graph, fpga_graph = graphs()
graph_seconds = time.perf_counter()-start
os.sched_setaffinity(0,{3})
timer = AudioTimer()
summary = []
for duration, filename in ((.5,'speech_05.wav'),(1,'speech_10.wav'),(2.5,'speech_25.wav')):
    audio_path = root/'reports/test-inputs'/filename
    audio = read_audio(audio_path)
    policy = next(x['policy'] for x in policies['selected'] if x['context_seconds']==duration)
    cpu_policy = policies['cpu_policies'][format(duration,'g')]
    configure_irqs(policy['irq_core'])
    start = time.perf_counter()
    physical = session(fpga_graph,policy,True)
    fpga_init = time.perf_counter()-start
    start = time.perf_counter()
    cpu = session(cpu_graph,cpu_policy)
    cpu_init = time.perf_counter()-start
    cold_fpga, cold_actual = timer.call(physical,audio,cold=True)
    cold_cpu, cold_expected = timer.call(cpu,audio,False)
    np.testing.assert_array_equal(cold_actual,cold_expected)
    def pair(index):
        if index%2:
            c,e = timer.call(cpu,audio,False)
            f,a = timer.call(physical,audio)
        else:
            f,a = timer.call(physical,audio)
            c,e = timer.call(cpu,audio,False)
        np.testing.assert_array_equal(a,e)
        if f['text'] != c['text'] or f['length'] != c['length']:
            raise RuntimeError('Text/length mismatch')
        return {'index':index,'order':'cpu-first' if index%2 else 'fpga-first',
                'cpu':c,'fpga':f,'logits_bit_exact':True}
    for i in range(10):
        pair(i)
    rows=[]
    for i in range(args.runs):
        rows.append(pair(i))
        if (i+1)%100==0:
            print(f'{duration}s: {i+1}/{args.runs} full-logit comparisons passed',flush=True)
    metrics={}
    for name in ('cpu','fpga'):
        values=np.array([r[name]['seconds'] for r in rows])
        metrics[name]={key:float(value) for key,value in zip(
            ('p50_ms','p95_ms','p99_ms','mean_ms','min_ms','max_ms'),
            np.r_[np.percentile(values,[50,95,99]),values.mean(),values.min(),values.max()]*1000)}
        metrics[name]['rtf_p50']=metrics[name]['p50_ms']/1000/duration
        for stage in ('frontend_seconds','model_seconds','decode_seconds'):
            metrics[name][stage.replace('_seconds','_p50_ms')]=float(np.median([r[name][stage] for r in rows])*1000)
    item={'audio_seconds':duration,'runs':args.runs,'warmup_pairs':10,
          'cpu_policy':cpu_policy,'fpga_policy':policy,'metrics':metrics,
          'speedup_p50':metrics['cpu']['p50_ms']/metrics['fpga']['p50_ms'],
          'latency_reduction_percent':100*(1-metrics['fpga']['p50_ms']/metrics['cpu']['p50_ms']),
          'all_logits_bit_exact':True,'text':rows[0]['fpga']['text'],
          'graph_build_seconds':graph_seconds,'fpga_session_init_seconds':fpga_init,
          'cpu_session_init_seconds':cpu_init,'cold_fpga':cold_fpga,'cold_cpu':cold_cpu,
          'audio_sha256':hashlib.sha256(audio_path.read_bytes()).hexdigest()}
    save('paired-'+format(duration,'g')+'s.json',{'summary':item,'rows':rows})
    summary.append(item)
    save('summary.json',{'onnxruntime':ort.__version__,'results':summary,
         'timing_scope':'frontend + model + greedy decode; excludes WAV file IO, initialization, firmware transitions and verification',
         'input_scope':'Three prefixes of one speech recording; no representative WER or live microphone qualification'})
    print(json.dumps({'duration':duration,'metrics':metrics,'speedup':item['speedup_p50']}),flush=True)
    del physical,cpu
    gc.collect()
save('environment-after.json',environment())
