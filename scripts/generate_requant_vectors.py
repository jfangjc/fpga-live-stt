"""Golden RTL vectors from the independently tested Python arithmetic oracle."""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'software/fused'))
from oracle import round_shift_even


def main():
    out = ROOT/'sim/fused_vectors'
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7026)
    inputs, expected = [], []
    for i in range(1024):
        acc = rng.integers(-(1 << 31), 1 << 31, 4, dtype=np.int64)
        mult = rng.integers(0, 1 << 31, 4, dtype=np.int64)
        shifts = rng.integers(1, 63, 4)
        masks = rng.integers(0, 2, 4); relus = rng.integers(0, 2, 4)
        if i < 16:
            acc = np.array([-5, -3, 3, 5], np.int64)
            mult[:] = 1; shifts[:] = 1; masks[:] = 1; relus[:] = i & 1
        if i == 16:
            acc = np.array([-(1 << 31), (1 << 31)-1, -127, 127], np.int64)
            mult[:] = (1 << 31)-1; shifts[:] = 1; masks[:] = 1; relus[:] = 0
        if i % 37 == 0 and i > 16:
            shifts[0] = 0; shifts[1] = 63; mult[2] = 1 << 31
        last = int(i % 17 == 16)
        tag = 0x70000000+i
        packed = sum((int(v)&0xffffffff) << (j*32) for j, v in enumerate(acc))
        packed |= sum(int(v) << (128+j*32) for j, v in enumerate(mult))
        packed |= sum(int(v) << (256+j*6) for j, v in enumerate(shifts))
        packed |= sum(int(v) << (280+j) for j, v in enumerate(masks))
        packed |= sum(int(v) << (284+j) for j, v in enumerate(relus))
        packed |= last << 288; packed |= tag << 289
        data, error = 0, 0
        for j in range(4):
            bad = shifts[j] in (0, 63) or mult[j] >= (1 << 31)
            error |= int(bad)
            value = 0
            if masks[j] and not bad:
                value = int(round_shift_even(np.array([int(acc[j])*int(mult[j])], np.int64), int(shifts[j]))[0])
                value = max(-127, min(127, value))
                if relus[j]: value = max(0, value)
            data |= (value & 255) << (j*8)
        inputs.append(f'{packed:081x}\n')
        expected.append(f'{data | error<<32 | last<<33 | tag<<34:017x}\n')
    (out/'input.mem').write_text(''.join(inputs))
    (out/'expected.mem').write_text(''.join(expected))
    files = [Path(__file__), ROOT/'software/fused/oracle.py', ROOT/'rtl/experimental/fused_requant.v',
             out/'input.mem', out/'expected.mem']
    (out/'provenance.json').write_text(json.dumps({'vectors': 1024, 'lanes': 4,
        'sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}, indent=2)+'\n')
    print('generated 1024 four-lane requantization vectors')


if __name__ == '__main__': main()
