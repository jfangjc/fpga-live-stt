"""Measure paired resident runners. No FPGA/model adapter is implicitly supplied."""
import argparse
from contextlib import ExitStack,contextmanager
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import statistics
import sys
import time
import unicodedata

def sha256(path):
    h = hashlib.sha256()
    with open(path,'rb') as stream:
        for chunk in iter(lambda:stream.read(1<<20),b''): h.update(chunk)
    return h.hexdigest()

def words(text):
    text = unicodedata.normalize('NFKC',text).lower()
    return re.sub(r"[^\w\s']",' ',text).split()

def errors(reference,hypothesis):
    """Minimum word edit distance; corpus denominator is reference word count."""
    ref,hyp = words(reference),words(hypothesis)
    prev = list(range(len(hyp)+1))
    for i,a in enumerate(ref,1):
        row = [i]
        for j,b in enumerate(hyp,1): row.append(min(row[-1]+1,prev[j]+1,prev[j-1]+(a!=b)))
        prev = row
    return prev[-1],len(ref)

def percentile(values,q):
    values = sorted(values)
    index = (len(values)-1)*q
    lo = int(index)
    return values[lo]+(values[min(lo+1,len(values)-1)]-values[lo])*(index-lo)

def environment():
    def read(path):
        try: return Path(path).read_text().strip()
        except OSError: return None
    return {'platform':platform.platform(),'machine':platform.machine(),
            'thermal_millicelsius':{str(p):read(p) for p in Path('/sys/class/thermal').glob('thermal_zone*/temp')},
            'cpu_frequency_khz':{str(p):read(p) for p in Path('/sys/devices/system/cpu').glob('cpu*/cpufreq/scaling_cur_freq')},
            'cpu_governor':{str(p):read(p) for p in Path('/sys/devices/system/cpu').glob('cpu*/cpufreq/scaling_governor')},
            'thread_environment':{k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')}}

@contextmanager
def resident_runners(factory,threads):
    """All successfully created runners close, including init/metadata failures."""
    runners,initialization={},{}
    with ExitStack() as cleanup:
        for mode in ('cpu','fpga'):
            start=time.perf_counter();runner=factory(mode,threads)
            cleanup.callback(runner.close)
            runners[mode]=runner;initialization[mode]=time.perf_counter()-start
        yield runners,initialization

def validate_execution(result,mode):
    if result.get('hardware_execution') is not (mode=='fpga'):
        raise ValueError('Per-call hardware execution identity mismatch: '+mode)
    if mode=='fpga':
        stats=result.get('dma',{})
        if not all(isinstance(stats.get(k),(int,float)) and math.isfinite(stats[k]) and stats[k]>0
                   for k in ('loads','runs','ioctls','tx_bytes','rx_bytes')):
            raise ValueError('Positive physical DMA work is required for every FPGA call')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adapter',required=True,help='Python module providing create_runner(mode,threads), described in README')
    parser.add_argument('--adapter-dir',type=Path,help='Directory containing the adapter, independent of PYTHONPATH/sudo environment')
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--threads',type=int,default=4)
    parser.add_argument('--repeats',type=int,default=20)
    parser.add_argument('--warmups',type=int,default=3)
    parser.add_argument('--pl-clock-hz',type=int,required=True,help='Physically verified clock setting, not a requested clock')
    args = parser.parse_args()
    if args.repeats<10 or args.warmups<1 or args.threads<1 or args.pl_clock_hz<1: parser.error('Need >=10 repeats, >=1 warmup and positive threads/clock')
    if platform.system()!='Linux' or platform.machine() not in ('aarch64','arm64'):
        raise RuntimeError('Physical benchmarking requires the ARM64 Linux KV260; host tests use test_evaluation.py')
    records = [json.loads(line) for line in args.manifest.read_text().splitlines() if line.strip()]
    ids = set()
    required_categories = {'quiet','accent','numbers','names','noise'}
    categories = set()
    for r in records:
        if r['id'] in ids or not words(r['text']) or r.get('split')!='evaluation': raise ValueError('Unique IDs, nonempty references and evaluation split required')
        ids.add(r['id']); categories.update(r['categories'])
        r['audio'] = str((args.manifest.parent/r['audio']).resolve())
        r['audio_sha256'] = sha256(r['audio'])
    if not records or not required_categories<=categories: raise ValueError('Held-out corpus must cover quiet, accent, numbers, names, noise')
    if args.adapter_dir:
        sys.path.insert(0,str(args.adapter_dir.resolve()))
    module = importlib.import_module(args.adapter)
    with resident_runners(module.create_runner,args.threads) as (runners,initialization):
        metadata = {mode:runner.metadata() for mode,runner in runners.items()}
        identity = ('model_sha256','tokenizer_sha256','preprocessing_id','decoder_id')
        for field in identity:
            if not metadata['cpu'].get(field) or metadata['cpu'][field]!=metadata['fpga'].get(field): raise ValueError('Runner identity mismatch/missing: '+field)
        for field in ('model_sha256','tokenizer_sha256'):
            if not re.fullmatch(r'[0-9a-f]{64}',metadata['cpu'][field]): raise ValueError('SHA256 required: '+field)
        calibration = metadata['fpga'].get('calibration_audio_sha256')
        if calibration is None: raise ValueError('Explicit calibration_audio_sha256 list required (empty for dynamic quantization)')
        if set(calibration)&{r['audio_sha256'] for r in records}: raise ValueError('Calibration/evaluation audio overlap')
        if metadata['cpu'].get('hardware_execution') is not False or metadata['fpga'].get('hardware_execution') is not True: raise ValueError('Explicit physical hardware execution required')
        for mode in runners:
            if metadata[mode].get('threads')!=args.threads or not metadata[mode].get('precision'): raise ValueError('Explicit precision and thread metadata required')
        samples = []
        for r in records:
            for _ in range(args.warmups):
                for mode,runner in runners.items():
                    validate_execution(runner.transcribe(r['audio']),mode)
            for repeat in range(args.repeats):
                modes = ['cpu','fpga']; random.Random(repeat).shuffle(modes)
                for mode in modes:
                    before = environment(); start = time.perf_counter()
                    result = runners[mode].transcribe(r['audio'])
                    elapsed = time.perf_counter()-start
                    validate_execution(result,mode)
                    if not math.isfinite(elapsed) or elapsed<=0 or not isinstance(result['transcript'],str): raise ValueError('Invalid runner result')
                    count,denom = errors(r['text'],result['transcript'])
                    samples.append({'id':r['id'],'mode':mode,'repeat':repeat,'total_seconds':elapsed,
                                    'word_errors':count,'reference_words':denom,'transcript':result['transcript'],
                                    'environment_before':before,'environment_after':environment(),'runner_details':result})
    summary = {}
    for mode in runners:
        selected = [s for s in samples if s['mode']==mode]
        values = [s['total_seconds'] for s in selected]
        # First repeat per utterance supplies corpus WER; repeats do not enlarge corpus.
        first = [s for s in selected if s['repeat']==0]
        summary[mode] = {'p50_seconds':statistics.median(values),'p95_seconds':percentile(values,.95),
                         'corpus_wer':sum(s['word_errors'] for s in first)/sum(s['reference_words'] for s in first),
                         'n_utterances':len(first),'n_warm_samples':len(values)}
    per_clip = {}
    for r in records:
        med = {mode:statistics.median([s['total_seconds'] for s in samples if s['id']==r['id'] and s['mode']==mode]) for mode in runners}
        per_clip[r['id']] = {**med,'reduction_fraction':1-med['fpga']/med['cpu']}
    reduction = 1-sum(p['fpga'] for p in per_clip.values())/sum(p['cpu'] for p in per_clip.values())
    degradation = summary['fpga']['corpus_wer']-summary['cpu']['corpus_wer']
    report = {'measured_on_physical_board':True,'initialization_seconds':initialization,'metadata':metadata,
              'pl_clock_hz':args.pl_clock_hz,'manifest_sha256':sha256(args.manifest),'corpus':records,
              'summary':summary,'per_clip':per_clip,'aggregate_time_reduction_fraction':reduction,
              'wer_degradation_absolute':degradation,'gates':{'speed':reduction>=.20,'accuracy':degradation<=.01},
              'existing_quartznet_10s_seconds':1.9651243530097418,'samples':samples,
              'limits':['Capture drop validation must be performed separately','Historical QuartzNet comparison requires identical 10-second speech.wav']}
    args.out.write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__': main()
