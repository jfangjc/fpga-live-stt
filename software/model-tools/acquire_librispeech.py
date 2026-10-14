#!/usr/bin/env python3
"""Download a deliberately small public read-speech regression/calibration set.

This does NOT cover quiet/noisy/accented/name/number gates or estimate corpus
WER. Test and validation samples never share recordings; both are held out
from pretrained LibriSpeech training. Raw FLAC and reference metadata retained.
"""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import soundfile as sf


def main():
    p=argparse.ArgumentParser(); p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--count',type=int,default=5); a=p.parse_args()
    if not 1<=a.count<=20: p.error('Small regression subset count must be 1..20')
    a.output_dir.mkdir(parents=True,exist_ok=True)
    provenance={'dataset':'openslr/librispeech_asr','config':'clean',
        'license':'CC-BY-4.0','source':'https://www.openslr.org/12/',
        'limitations':'Small consecutive read-speech samples, not representative corpus WER; requested microphone categories absent',
        'splits':{}}
    for split,role in [('validation','calibration'),('test','evaluation')]:
        endpoint=f'https://datasets-server.huggingface.co/rows?dataset=openslr%2Flibrispeech_asr&config=clean&split={split}&offset=0&length={a.count}'
        metadata=json.load(urllib.request.urlopen(endpoint))
        (a.output_dir/f'{role}_source_rows.json').write_text(json.dumps(metadata,indent=2))
        directory=a.output_dir/role; directory.mkdir(exist_ok=True)
        manifest=[]
        for item in metadata['rows']:
            row=item['row']; name=row['id']; url=row['audio'][0]['src']
            flac=directory/f'{name}.flac'; flac.write_bytes(urllib.request.urlopen(url).read())
            samples,rate=sf.read(flac,dtype='int16')
            if rate!=16000 or samples.ndim!=1: raise ValueError('Unexpected LibriSpeech audio format')
            wav=directory/f'{name}.wav'; sf.write(wav,samples,rate,subtype='PCM_16')
            manifest.append({'id':name,'audio':f'{role}/{name}.wav','reference':row['text'].lower(),
                'role':role,'category':'read_speech','speaker_id':row['speaker_id'],
                'flac_sha256':hashlib.sha256(flac.read_bytes()).hexdigest(),
                'wav_sha256':hashlib.sha256(wav.read_bytes()).hexdigest(),'duration_seconds':len(samples)/rate})
        (a.output_dir/f'{role}.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in manifest))
        provenance['splits'][role]={'split':split,'count':len(manifest),'ids':[r['id'] for r in manifest]}
    if set(provenance['splits']['calibration']['ids']) & set(provenance['splits']['evaluation']['ids']):
        raise ValueError('Calibration/evaluation leak')
    (a.output_dir/'PROVENANCE.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps(provenance,indent=2))


if __name__=='__main__': main()
