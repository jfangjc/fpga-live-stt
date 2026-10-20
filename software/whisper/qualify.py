"""Bind final physical, latency and English accuracy evidence into one report."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from model_spec import SPECS


def load(path):
    return json.loads(path.read_text())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work',type=Path,required=True)
    ap.add_argument('--max-wer-increase',type=float,default=0.01)
    ap.add_argument('--out',type=Path,required=True)
    a = ap.parse_args()
    if a.out.exists():
        ap.error('Refusing to overwrite qualification evidence')
    work = a.work.resolve()
    latency = load(work/'latency_results/results.json')
    validation = load(work/'validation_results/results.json')
    wer = load(work/'validation_wer.json')
    arithmetic = load(work/'parallel_conformance.json')
    gates = {}
    gates['repeated_latency'] = latency['repeats']>=3 and len(latency['clips'])>=3
    gates['all_clips_2x_p50'] = all(row['speedup']>=2 for row in latency['clips'])
    gates['same_dynamic_libraries'] = latency['dynamic_libraries']==validation['dynamic_libraries']
    identity = latency.get('model','openai/whisper-base')
    if identity in ('openai/whisper-large-v3-turbo','openai/whisper-small'):
        gates['artifacts_stable_during_runs'] = all(result.get('artifacts_unchanged_after_run',False) for result in (latency,validation))
    gates['same_model_architecture'] = identity==validation.get('model','openai/whisper-base')
    expected_models = {'model-base.bin':'60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe',
        'model-base-q8_0.bin':'c577b9a86e7e048a0b7eada054f4dd79a56bbfa911fbdacf900ac5b567cbb7d9',
        'model-base-q5_0.bin':'64a4aa8c82f4cdf066fa0d605400e7e5086f9b7992f2e5f638faaee1b3dae25c'}
    provenance_path = work/'model_manifest.json'
    if provenance_path.exists():
        provenance = load(provenance_path)
        spec = next(spec for spec in SPECS.values() if spec['id']==identity)
        gates['verified_source_checkpoint'] = provenance['model']==identity and provenance['source_sha1']==spec['source_sha1']
        expected_models = {Path(path).name:entry['sha256'] for path,entry in provenance['models'].items()}
        short = identity.removeprefix('openai/whisper-')
        gates['three_comparator_formats'] = set(expected_models)=={
            f'ggml-{short}{suffix}.bin' for suffix in ('','-q8_0','-q5_0')}
    else:
        gates['verified_source_checkpoint'] = identity=='openai/whisper-base'
    gates['checkpoint_identity'] = True
    for label,result in (('latency',latency),('validation',validation)):
        actual = {Path(path).name:digest for path,digest in result['artifacts'].items()}
        required = set(expected_models)
        if label=='validation' and provenance_path.exists():
            # Accuracy is against FP16; the repeated timing sweep screens all formats.
            required = {f'ggml-{short}.bin',f'ggml-{short}-q8_0.bin'}
        if any(actual.get(name)!=expected_models[name] for name in required):
            gates['checkpoint_identity'] = False
    gates['exact_arithmetic'] = arithmetic['passed'] and any(row.get('ggml_parallel_4_exact') for row in arithmetic['cases'])
    gates['physical_attention'] = True
    gates['complete_selected_partition'] = True
    expected_partition = {'openai/whisper-base':(60,12,252),
                          'openai/whisper-small':(120,24,720),
                          'openai/whisper-large-v3-turbo':(264,64,3744)}[identity]
    for result in (latency,validation):
        for clip in result['clips']:
            for row in clip['rows']['hybrid']:
                log = (work/row['log']).read_text()
                match = re.search(r'KV260_STATS calls=(\d+).*ioctls=(\d+).*attention_calls=(\d+)',log)
                if not match or min(map(int,match.groups()))<=0:
                    gates['physical_attention'] = False
                loads = re.search(r'loads=(\d+)',log)
                if not match or not loads or (int(match[1]),int(match[3]),int(loads[1]))!=expected_partition:
                    gates['complete_selected_partition'] = False
    sessions = {name:load(work/name) for name in ('parallel_session.json','validation_session.json','latency_session.json')}
    gates['board_restored'] = all(row['restored'] for row in sessions.values())
    reference = wer['totals']['cpu_0_no_flash']['wer']
    hybrid = wer['totals']['hybrid']['wer']
    gates['english_wer_sample'] = len(wer['clips'])>=10 and hybrid-reference<=a.max_wer_increase
    evidence = {}
    for name in ('latency_results/results.json','validation_results/results.json','validation_wer.json',
                 'parallel_conformance.json','parallel_session.json','validation_session.json','latency_session.json'):
        evidence[name] = hashlib.sha256((work/name).read_bytes()).hexdigest()
    if provenance_path.exists():
        evidence['model_manifest.json'] = hashlib.sha256(provenance_path.read_bytes()).hexdigest()
    summary = {'model':identity,'prototype_gates_passed':all(gates.values()),'production_qualified':False,'gates':gates,
        'latency': [{'audio':Path(row['audio']).name,'best_cpu':row['best_cpu'],
                     'cpu':row['summary'][row['best_cpu']],'hybrid':row['summary']['hybrid'],
                     'speedup_p50':row['speedup'],
                     'speedup_p95':row['summary'][row['best_cpu']]['p95_seconds']/row['summary']['hybrid']['p95_seconds']}
                    for row in latency['clips']],
        'accuracy':{'clips':len(wer['clips']),'reference_words':wer['totals']['hybrid']['reference_words'],
                    'cpu_fp16_wer':reference,'hybrid_wer':hybrid,'absolute_wer_increase':hybrid-reference,
                    'maximum_allowed_increase':a.max_wer_increase,'totals':wer['totals']},
        'timing_scope':latency['scope']+'; FPGA activation/restoration separate',
        'evidence_sha256':evidence,
        'limits':['Small English read-speech sample','Multilingual/noisy/long-form corpus accuracy unqualified',
                  'One model/context per process','CPU comparison limited to pinned whisper.cpp runtime',
                  'p95 descriptive with three measured runs per configuration']}
    a.out.write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    if not summary['prototype_gates_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
