"""Compare the integer specification with native float32 and write RTL fixtures."""
import hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'software/latency'))
from exact_requant_reference import requant
rng=np.random.default_rng(20261012)
count=1000000
acc=rng.integers(-(1<<31),(1<<31),count,dtype=np.int64)
mult=(rng.integers(1<<23,1<<24,count,dtype=np.uint64)<<np.uint64(7))
shift=rng.integers(1,63,count,dtype=np.uint64);zero=rng.integers(0,256,count,dtype=np.uint64)
scale=np.ldexp(mult.astype(np.float32),-shift.astype(np.int32))
product=acc.astype(np.float32)*scale
expected=np.clip(np.rint(product).astype(np.float64)+zero.astype(np.float64),0,255).astype(np.uint8)
actual=requant(acc,mult,shift,zero);np.testing.assert_array_equal(actual,expected)
# Products intentionally near half-integers expose the old single-rounding difference.
target_acc=rng.integers(1,1<<31,100000,dtype=np.int64)
ratio=((rng.integers(0,255,100000)+.5)/target_acc.astype(np.float32)).astype(np.float32)
mant,exp=np.frexp(ratio);tm=np.rint(mant.astype(np.float64)*(1<<31)).astype(np.uint64);ts=(31-exp).astype(np.uint64)
tz=rng.integers(0,256,100000,dtype=np.uint64);target_acc*=rng.choice([-1,1],100000)
expected_ties=np.clip(np.rint(target_acc.astype(np.float32)*ratio).astype(np.int64)+tz,0,255).astype(np.uint8)
actual_ties=requant(target_acc,tm,ts,tz);np.testing.assert_array_equal(actual_ties,expected_ties)
single_product=target_acc*tm.astype(np.int64);q=single_product>>ts.astype(np.int64)
r=single_product-q*(np.int64(1)<<ts.astype(np.int64));half=np.int64(1)<<(ts.astype(np.int64)-1)
single=np.clip(q+((r>half)|((r==half)&((q&1)!=0)))+tz.astype(np.int64),0,255).astype(np.uint8)
disagreements=int(np.count_nonzero(single!=expected_ties));assert disagreements>1000
fixtures=ROOT/'verification/exact-requant';fixtures.mkdir(parents=True,exist_ok=True)
lines=[]
for row in range(2400):
    bits=0;error=False
    for lane in range(4):
        i=row*4+lane
        if row<1200:a=int(acc[i]);m=int(mult[i]);s=int(shift[i]);z=int(zero[i])
        else:a=int(target_acc[i]);m=int(tm[i]);s=int(ts[i]);z=int(tz[i])
        b=0
        if row%37==0:b=-(1<<30) if lane%2 else (1<<30)-1
        if row%41==0 and lane==0:m|=1
        if row%43==0 and lane==1:s=0
        if row%47==0 and lane==2:s=63
        if row%53==0 and lane==3:m|=1<<31
        total=a+b;bad=total<-(1<<31) or total>(1<<31)-1 or m>>31 or m&127 or s==0 or s==63
        out=0 if bad else int(requant(np.array([total]),np.array([m],np.uint64),np.array([s],np.uint64),np.array([z]))[0])
        error|=bool(bad)
        bits|=(a&0xffffffff)<<(lane*32);bits|=(b&0xffffffff)<<(128+lane*32);bits|=m<<(256+lane*32)
        bits|=s<<(384+lane*6);bits|=z<<(408+lane*8);bits|=out<<(440+lane*8)
    bits|=int(error)<<472;lines.append(f'{bits:0128x}\n')
path=fixtures/'quant.mem';path.write_text(''.join(lines))
proof={'complete':True,'hardware_execution':False,'random_cases':count,'targeted_half_cases':len(target_acc),'all_float32_bit_exact':True,
       'single_rounding_disagreements':disagreements,'rtl_vectors':len(lines),
       'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
       'reference_sha256':hashlib.sha256((ROOT/'software/latency/exact_requant_reference.py').read_bytes()).hexdigest(),
       'fixture_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
(ROOT/'reports/fused/exact_requant_integer_validation.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
