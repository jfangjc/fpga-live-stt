"""Retest hybrid accuracy while reusing verified unchanged CPU reference runs.

Performance qualification uses fresh paired latency_results separately.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
from benchmark import dependencies,run,sha,summarize


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--prior',required=True,type=Path)
    ap.add_argument('--cpu',required=True,type=Path)
    ap.add_argument('--hybrid',required=True,type=Path)
    ap.add_argument('--model',required=True,type=Path)
    ap.add_argument('--out',required=True,type=Path)
    a = ap.parse_args()
    previous = json.loads(a.prior.read_text())
    if dependencies(a.cpu)!=previous['dynamic_libraries']['cpu']:
        raise RuntimeError('CPU reference libraries changed; rerun CPU references')
    if sha(a.cpu)!=previous['artifacts'][str(a.cpu)] or sha(a.model)!=previous['artifacts'][str(a.model)]:
        raise RuntimeError('CPU/model identity changed; rerun references')
    for clip in previous['clips']:
        if sha(Path(clip['audio']))!=previous['artifacts'][clip['audio']]:
            raise RuntimeError('Validation audio changed')
    a.out.mkdir(parents=True,exist_ok=False)
    result = copy.deepcopy(previous)
    result['clips'] = []
    result['dynamic_libraries']['hybrid'] = dependencies(a.hybrid)
    result['artifacts'][str(a.hybrid)] = sha(a.hybrid)
    result['scope'] = 'Accuracy refresh; verified unchanged CPU reference runs reused. Fresh paired performance is in latency_results.'
    result['cpu_reference_reuse'] = {'source_report_sha256':sha(a.prior),
                                    'cpu_dynamic_libraries':dependencies(a.cpu),
                                    'reason':'Only the hybrid changed; CPU executable, libraries, model and WAV bytes are unchanged'}
    for i,old in enumerate(previous['clips']):
        clip = copy.deepcopy(old)
        for variant,rows in clip['rows'].items():
            if variant!='hybrid':
                for row in rows:
                    source = a.prior.parent/Path(row['log']).name
                    target = a.out/source.name
                    shutil.copyfile(source,target)
                    row['log'] = str(target)
                    row['reference_reused'] = True
        row = run(a.hybrid,a.model,Path(clip['audio']),previous['threads'],True,
                  a.out/f'{i}_0_hybrid.log',fpga_attention=True,flash_attention=False)
        print(json.dumps({'clip':clip['audio'],'variant':'hybrid',**row}),flush=True)
        clip['rows']['hybrid'] = [row]
        clip['summary']['hybrid'] = summarize([row])
        clip['speedup'] = clip['summary'][clip['best_cpu']]['p50_seconds']/row['seconds']
        clip['timing_2x'] = clip['speedup']>=2
        clip['text_parity'] = row['text']==clip['rows']['cpu_0_no_flash'][0]['text']
        result['clips'].append(clip)
        (a.out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    result['all_clips_timing_2x'] = all(row['timing_2x'] for row in result['clips'])
    (a.out/'results.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__ == '__main__':
    main()
