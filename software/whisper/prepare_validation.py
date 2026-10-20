"""Select ten speakers from the official LibriSpeech test-clean archive.

Needs numpy/soundfile only during data preparation. Uses two streaming archive
passes; never extracts archive paths to the filesystem. No quality-based choice.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import random
import re
import tarfile
from urllib.parse import urlencode,urlparse
from urllib.request import urlopen
import soundfile as sf


def digest(path, algorithm='sha256'):
    with path.open('rb') as f:
        return hashlib.file_digest(f,algorithm).hexdigest()


def prepare_api(out):
    endpoint = 'https://datasets-server.huggingface.co/rows?'
    def fetch(offset):
        url = endpoint+urlencode({'dataset':'openslr/librispeech_asr','config':'clean','split':'test','offset':offset,'length':1})
        with urlopen(url,timeout=30) as response:
            return json.load(response)
    first = fetch(0)
    offsets = list(range(first['num_rows_total']))
    random.Random(260).shuffle(offsets)
    out.mkdir(parents=True,exist_ok=False);(out/'audio').mkdir()
    rows,seen,revisions = [],{6930,2277},set()
    for offset in offsets:
        item = fetch(offset)['rows'][0]['row']
        speaker = int(item['speaker_id'])
        if speaker in seen:
            continue
        identity = item['id']
        if not re.fullmatch(r'\d+-\d+-\d+',identity):
            raise ValueError('Unexpected dataset identity')
        url = item['audio'][0]['src']
        parsed = urlparse(url)
        if parsed.scheme!='https' or not parsed.hostname.endswith('.huggingface.co'):
            raise ValueError('Unexpected public dataset audio host')
        revisions.update(re.findall(r'/--/([0-9a-f]{40})/--/',url))
        if len(revisions)>1:
            raise ValueError('Dataset revision changed during sampling')
        with urlopen(url,timeout=30) as response:
            contents = response.read()
        info = sf.info(io.BytesIO(contents))
        if not (3<=info.duration<=28 and info.samplerate==16000 and info.channels==1):
            continue
        signal,rate = sf.read(io.BytesIO(contents),dtype='int16')
        wav = out/'audio'/f'{identity}.wav';sf.write(wav,signal,rate,subtype='PCM_16')
        row = {'id':identity,'audio':f'audio/{identity}.wav','reference':item['text'].lower(),
               'role':'evaluation','category':'read_speech','speaker_id':speaker,'row_index':offset,
               'duration_seconds':info.duration,'wav_sha256':digest(wav),
               'flac_sha256':hashlib.sha256(contents).hexdigest()}
        rows.append(row);seen.add(speaker);print(json.dumps(row),flush=True)
        if len(rows)==10:
            break
    if len(rows)!=10:
        raise ValueError('Could not obtain ten distinct speakers')
    (out/'evaluation.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    provenance = {'source':'https://www.openslr.org/12/','mirror':'https://huggingface.co/datasets/openslr/librispeech_asr',
        'license':'CC-BY-4.0','split':'test-clean','dataset_revisions':sorted(revisions),'seed':260,
        'count':10,'speakers':sorted(seen-{6930,2277}),
        'selection':'Seeded random row order; ten distinct speakers excluding prior engineering/calibration speakers; 3-28 s duration',
        'limitations':'Small English read-speech engineering sample; production, multilingual and noisy accuracy unqualified'}
    (out/'PROVENANCE.json').write_text(json.dumps(provenance,indent=2)+'\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('archive',type=Path,nargs='?',help='Optional official archive; default uses public dataset rows/audio API')
    ap.add_argument('--out',required=True,type=Path)
    a = ap.parse_args()
    if a.archive is None:
        prepare_api(a.out)
        return
    if digest(a.archive,'md5') != '32fa31d27d2e1cad72775fee3f4849a9':
        raise ValueError('Official archive checksum mismatch')
    grouped = {}
    with tarfile.open(a.archive,'r|gz') as tar:
        for member in tar:
            parts = member.name.split('/')
            if len(parts)==5 and parts[:2]==['LibriSpeech','test-clean'] and member.name.endswith('.flac'):
                speaker = int(parts[2])
                if speaker not in (6930,2277):
                    grouped.setdefault(speaker,[]).append(member.name)
    rng = random.Random(260)
    speakers = sorted(rng.sample(sorted(grouped),10))
    candidates = {}
    for speaker in speakers:
        files = sorted(grouped[speaker]);rng.shuffle(files)
        candidates[speaker] = files[:3]
    selected_names = {p for files in candidates.values() for p in files}
    data, references = {}, {}
    with tarfile.open(a.archive,'r|gz') as tar:
        for member in tar:
            if member.name in selected_names:
                data[member.name] = tar.extractfile(member).read()
            elif member.isfile() and member.name.endswith('.trans.txt'):
                for line in tar.extractfile(member).read().decode('utf-8').splitlines():
                    identity,text = line.split(' ',1)
                    references[identity] = text.lower()
    a.out.mkdir(parents=True,exist_ok=False)
    (a.out/'audio').mkdir()
    rows = []
    for speaker in speakers:
        for name in candidates[speaker]:
            contents = data[name]
            info = sf.info(io.BytesIO(contents))
            if 3 <= info.duration <= 28 and info.samplerate==16000 and info.channels==1:
                identity = Path(name).stem
                if not re.fullmatch(r'\d+-\d+-\d+',identity):
                    raise ValueError('Unexpected archive identity')
                signal,rate = sf.read(io.BytesIO(contents),dtype='int16')
                wav = a.out/'audio'/f'{identity}.wav'
                sf.write(wav,signal,rate,subtype='PCM_16')
                rows.append({'id':identity,'audio':f'audio/{identity}.wav','reference':references[identity],
                    'role':'evaluation','category':'read_speech','speaker_id':speaker,
                    'duration_seconds':info.duration,'wav_sha256':digest(wav),
                    'flac_sha256':hashlib.sha256(contents).hexdigest()})
                break
        else:
            raise ValueError(f'No candidate in declared duration range for speaker {speaker}')
    (a.out/'evaluation.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    provenance = {'source':'https://www.openslr.org/12/','license':'CC-BY-4.0','split':'test-clean',
        'archive_md5':digest(a.archive,'md5'),'archive_sha256':digest(a.archive),
        'seed':260,'speakers':speakers,'count':len(rows),
        'selection':'10 random speakers excluding prior engineering/calibration speakers; first of 3 randomized candidates lasting 3-28 s',
        'limitations':'Small English read-speech engineering sample; does not qualify production or multilingual/noisy accuracy'}
    (a.out/'PROVENANCE.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps(provenance,indent=2))


if __name__ == '__main__':
    main()
