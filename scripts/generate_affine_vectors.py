"""Unbounded-integer golden affine rounding and overflow fixtures."""
import hashlib,json,random
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    rng=random.Random(202610092);inputs=[];expected=[]
    for i in range(1024):
        a=rng.randrange(-2**31,2**31);b=rng.randrange(-2**31,2**31)
        multiplier=rng.randrange(2**31);shift=rng.randrange(1,63);zero=rng.randrange(256)
        if i<32:a=i-16;b=0;multiplier=1;shift=1;zero=128
        if i==32:a=2**31-1;b=1
        if i==33:a=-2**31;b=-1
        if i==34:a=-2**31;b=0;multiplier=2**31-1;shift=62
        if i==35:a=2**31-1;b=0;multiplier=2**31-1;shift=62
        if i%73==40:shift=0
        if i%73==41:shift=63
        if i%73==42:multiplier=2**31
        bad=not -2**31<=a+b<2**31 or multiplier>=2**31 or shift not in range(1,63)
        result=0
        if not bad:
            quotient,remainder=divmod((a+b)*multiplier,1<<shift)
            quotient+=int(2*remainder>1<<shift or (2*remainder==1<<shift and quotient%2))
            result=max(0,min(255,quotient+zero))
        inputs.append((a&0xffffffff)|((b&0xffffffff)<<32)|(multiplier<<64)|(shift<<96)|(zero<<102))
        expected.append(result|(int(bad)<<8))
    out=ROOT/'sim/affine_vectors';out.mkdir(parents=True,exist_ok=True)
    (out/'input.mem').write_text(''.join(f'{v:028x}\n' for v in inputs))
    (out/'expected.mem').write_text(''.join(f'{v:03x}\n' for v in expected))
    metadata={'vectors':len(inputs),'oracle':'Python unbounded integer divmod',
              'physical_hardware_execution':False,
              'sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in (Path(__file__),ROOT/'rtl/experimental/fused_affine_quant.v',out/'input.mem',out/'expected.mem')}}
    (out/'provenance.json').write_text(json.dumps(metadata,indent=2)+'\n')


if __name__=='__main__':main()
