"""Independent scalar reduction fixtures, including the real block SE input."""
import hashlib
import json
from pathlib import Path
import random
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT/'sim/se_vectors'
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261009)
    inputs, expected = [], []

    def packet(beats, tag, bad_start=False, bad_tag=False, duplicate=False):
        total, count, error = 0, 0, bad_start
        for i, (data, mask) in enumerate(beats):
            start = i == 0 and not bad_start or duplicate and i == 1
            current_tag = tag ^ (1 if bad_tag and i == 1 else 0)
            error |= i > 0 and (start or current_tag != tag)
            for v, valid in zip(data, mask):
                if valid:
                    total += v
                    count += 1
                    error |= v == -128
            error |= count > 1024
            packed = sum((v & 255) << (8*j) for j, v in enumerate(data))
            packed |= sum(int(v) << (128+j) for j, v in enumerate(mask))
            packed |= current_tag << 144
            packed |= int(start) << 176
            packed |= int(i == len(beats)-1) << 177
            inputs.append(packed)
        expected.append((tag << 65) | (int(error) << 64) |
                        ((0 if error else count) << 32) |
                        ((0 if error else total) & 0xffffffff))

    for p in range(256):
        beats = [([rng.randint(-127,127) for _ in range(16)],
                  [rng.randrange(2) for _ in range(16)])
                 for _ in range(1+p % 7)]
        if p == 0: beats = [([-128]*16, [False]*16)]
        if p == 1: beats = [([-128]*16, [True]*16)]
        if p == 2: beats = [([127]*16, [True]*16)]*64  # exact bound
        if p == 3: beats = [([-127]*16, [True]*16)]*65 # over bound
        packet(beats, 0x53000000+p, bad_start=p%29==5,
               bad_tag=p%31==6, duplicate=p%37==7)

    # Use the exported model's actual INT8 SE input when available.
    vector_path = ROOT/'research/fused/block-vectors/vectors.npz'
    manifest = json.loads((vector_path.parent/'manifest.json').read_text())
    vectors = np.load(vector_path)
    se_info = manifest['se_reductions'][0]
    prefix = se_info['prefix']
    q = vectors[prefix+'_input']
    for channel in range(q.shape[1]):
        values = [int(v) for v in q[0, channel]]
        beats = []
        for start in range(0,len(values),16):
            valid = min(16,len(values)-start)
            beats.append((values[start:start+16]+[0]*(16-valid),
                          [True]*valid+[False]*(16-valid)))
        packet(beats, 0x54000000+channel)
        # Check scalar expectations against the independently generated oracle sum.
        assert (expected[-1] & 0xffffffff) == (int(vectors[prefix+'_sum'].reshape(-1)[channel]) & 0xffffffff)
    (out/'input.mem').write_text(''.join(f'{v:045x}\n' for v in inputs))
    (out/'expected.mem').write_text(''.join(f'{v:025x}\n' for v in expected))
    (out/'counts.vh').write_text(f'localparam INPUT_COUNT={len(inputs)};\nlocalparam OUTPUT_COUNT={len(expected)};\n')
    report = {'input_beats':len(inputs), 'output_packets':len(expected),
              'lanes':16,'test_max_samples':1024,'real_se_channels':int(q.shape[1]),
              'real_se_vector_sha256':hashlib.sha256(vector_path.read_bytes()).hexdigest(),
              'physical_hardware_execution':False}
    report['sources_sha256'] = {str(p.relative_to(ROOT).as_posix()):hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (Path(__file__),ROOT/'rtl/experimental/fused_se_reduce.v')}
    for name in ('input.mem','expected.mem'):
        report[name+'_sha256'] = hashlib.sha256((out/name).read_bytes()).hexdigest()
    (out/'provenance.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
