"""Reproducible correlated quiet/noise diagnostics, not a representative corpus."""
from pathlib import Path
import hashlib
import json
import sys
import wave
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'software/model-tools'))
from citrinet_cpu import read_audio


def main():
    source = ROOT/'research/eval/user-recording/speech.wav'
    reference = json.loads((source.parent/'evaluation.jsonl').read_text())
    audio = read_audio(source)
    out = ROOT/'research/eval/user-stress-ac'
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(29102026)
    noise = rng.normal(size=len(audio)).astype(np.float32)
    noise /= np.sqrt(np.mean(noise.astype(np.float64)**2))
    mean = float(np.mean(audio.astype(np.float64)))
    total_rms = float(np.sqrt(np.mean(audio.astype(np.float64)**2)))
    # DC energy is not varying speech energy. Do not alter the original signal;
    # remove its mean only for defining the noise power used by this diagnostic.
    rms = float(np.sqrt(np.mean((audio.astype(np.float64)-mean)**2)))
    variants = [('quiet-minus20db', audio*np.float32(.1), {'gain_db': -20}, 'quiet')]
    for snr in (20, 10):
        variants.append(('noise-snr'+str(snr), audio+noise*np.float32(rms/(10**(snr/20))),
                         {'noise': 'seeded Gaussian', 'snr_db': snr, 'seed': 29102026,
                          'snr_reference': 'AC power; original input DC preserved'}, 'noise'))
    records = []
    for name, values, transform, category in variants:
        clipped = int(np.count_nonzero(np.abs(values) >= 1))
        if clipped:
            raise ValueError('Stress augmentation clips PCM range: '+name)
        integers = np.clip(np.rint(values.astype(np.float64)*8388608), -8388608, 8388607).astype('<i4')
        pcm = integers.view(np.uint8).reshape(-1, 4)[:, :3].copy().tobytes()
        path = out/(name+'.wav')
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(3); wav.setframerate(16000); wav.writeframes(pcm)
        records.append({'id': 'user-ac-'+name, 'audio': path.name, 'text': reference['text'],
                        'split': 'evaluation', 'categories': [category], 'synthetic_stress': True,
                        'reference_status': reference['reference_status'], 'transform': transform,
                        'source_audio_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                        'wav_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (out/'evaluation.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    (out/'PROVENANCE.json').write_text(json.dumps({'purpose': 'correlated stress regression only',
        'independent_utterances': 1, 'representative_corpus': False,
        'source_mean': mean, 'source_total_rms': total_rms, 'source_ac_rms': rms,
        'source': str(source.relative_to(ROOT)), 'transforms': [r['transform'] for r in records]}, indent=2)+'\n')
    print('generated 3 correlated quiet/noise diagnostics; no new independent speakers')
    legacy = ROOT/'research/eval/user-stress/PROVENANCE.json'
    if legacy.is_file():
        old = json.loads(legacy.read_text())
        old['snr_reference'] = 'Total waveform power including DC; legacy diagnostic'
        old['source_mean'] = mean; old['source_total_rms'] = total_rms; old['source_ac_rms'] = rms
        old['equivalent_ac_snr_db'] = {str(s): float(s+20*np.log10(rms/total_rms)) for s in (20, 10)}
        legacy.write_text(json.dumps(old, indent=2)+'\n')


if __name__ == '__main__': main()
