"""Compute corpus word errors from saved benchmark transcripts, without rerunning.

English normalization is lowercase alphanumeric words with internal apostrophes.
This is explicitly a simple normalization, not Whisper's EnglishTextNormalizer.
"""
import argparse
import json
from pathlib import Path
import re


def words(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)*", text.lower())


def errors(reference, hypothesis):
    previous = list(range(len(hypothesis)+1))
    for i, expected in enumerate(reference,1):
        current = [i]
        for j, actual in enumerate(hypothesis,1):
            current.append(min(previous[j]+1, current[-1]+1, previous[j-1]+(expected != actual)))
        previous = current
    return previous[-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('results',type=Path)
    ap.add_argument('--manifest',required=True,type=Path)
    ap.add_argument('--out',required=True,type=Path)
    a = ap.parse_args()
    if a.out.exists():
        ap.error('Refusing to overwrite evaluation evidence')
    manifest = [json.loads(line) for line in a.manifest.read_text().splitlines() if line.strip()]
    references = {Path(row['audio']).name: row for row in manifest}
    if len(references) != len(manifest):
        raise ValueError('Ambiguous manifest audio filenames')
    totals = {}
    clips = []
    result = json.loads(a.results.read_text())
    seen = set()
    for clip in result['clips']:
        row = references[Path(clip['audio']).name]
        if row['role'] != 'evaluation':
            raise ValueError('Evaluation must not include calibration audio')
        identity = result['artifacts'][clip['audio']]
        if identity != row['wav_sha256'] or identity in seen:
            raise ValueError('Audio hash mismatch or duplicate evaluation audio')
        seen.add(identity)
        reference = words(row['reference'])
        if not reference:
            raise ValueError('Empty reference')
        scores = {}
        for variant, runs in clip['rows'].items():
            # One transcript per clip avoids counting repeated timings as new audio.
            texts = {r['text'] for r in runs}
            if len(texts) != 1:
                raise ValueError('Nondeterministic transcript; inspect every run before scoring')
            score = errors(reference,words(next(iter(texts))))
            scores[variant] = {'word_errors':score,'reference_words':len(reference)}
            total = totals.setdefault(variant,{'word_errors':0,'reference_words':0})
            total['word_errors'] += score
            total['reference_words'] += len(reference)
        clips.append({'id':row['id'],'scores':scores})
    for total in totals.values():
        total['wer'] = total['word_errors']/total['reference_words']
    a.out.write_text(json.dumps({'normalization': 'English lowercase alphanumeric/apostrophe words',
                                 'clips':clips,'totals':totals},indent=2)+'\n')


if __name__ == '__main__':
    main()
