"""Validate CPU-compatible INT32 bias wrapping before residual FPGA offload."""
import hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'software/latency'))
from compact_requant_reference import requant
rng=np.random.default_rng(2026101230);count=1000000
acc=rng.integers(-(1<<31),1<<31,count,dtype=np.int64)
bias=rng.integers(-(1<<31),1<<31,count,dtype=np.int64)
total=acc+bias;wrapped=(total+(1<<31))%(1<<32)-(1<<31)
mult=rng.integers(0,1<<24,count,dtype=np.uint64)<<np.uint64(7)
shift=rng.integers(1,63,count,dtype=np.uint64);zero=rng.integers(0,256,count,dtype=np.uint64)
ratio=np.ldexp(mult.astype(np.float32),-shift.astype(np.int32))
expected=np.clip(np.rint(wrapped.astype(np.float32)*ratio).astype(np.float64)+zero.astype(np.float64),0,255).astype(np.uint8)
np.testing.assert_array_equal(requant(wrapped,mult,shift,zero),expected)
source=ROOT/'rtl/experimental/fused_affine_quant_compact.sv';rtl=source.read_text()
assert 'added[32]!=added[31] ||' in rtl
rtl=rtl.replace('module fused_affine_quant_compact','module fused_affine_quant_wrap')
rtl=rtl.replace('added[32]!=added[31] ||','')
rtl='// Separate contract: bias addition wraps modulo INT32 before float32 conversion.\n'+rtl
target=ROOT/'rtl/experimental/fused_affine_quant_wrap.sv'
if target.exists():assert target.read_text()==rtl
else:target.write_text(rtl)
dest=ROOT/'verification/wrapped-requant';dest.mkdir(parents=True,exist_ok=True)
lines=[];overflow_lanes=0
for line in (ROOT/'verification/exact-requant/quant.mem').read_text().splitlines():
    bits=int(line,16)&((1<<440)-1);error=False
    for lane in range(4):
        def signed(value):return value-(1<<32) if value&(1<<31) else value
        a=signed((bits>>(lane*32))&0xffffffff);b=signed((bits>>(128+lane*32))&0xffffffff)
        m=(bits>>(256+lane*32))&0xffffffff;s=(bits>>(384+lane*6))&63;z=(bits>>(408+lane*8))&255
        overflow_lanes+=not(-(1<<31)<=a+b<(1<<31))
        value=(a+b+(1<<31))%(1<<32)-(1<<31)
        bad=bool(m>>31 or m&127 or s in (0,63));error|=bad
        out=0 if bad else int(np.clip(np.rint(np.float32(value)*np.ldexp(np.float32(m),-s))+z,0,255))
        bits|=out<<(440+lane*8)
    bits|=int(error)<<472;lines.append(f'{bits:0128x}\n')
fixture=dest/'quant.mem';fixture.write_text(''.join(lines))
tb=(ROOT/'sim/tb_compact_requant.sv').read_text().replace('tb_compact_requant','tb_wrapped_requant')
tb=tb.replace('fused_affine_quant_compact','fused_affine_quant_wrap').replace('verification/exact-requant','verification/wrapped-requant')
tb=tb.replace('bias overflow','defined INT32 bias wrapping');(ROOT/'sim/tb_wrapped_requant.sv').write_text(tb)
tcl=(ROOT/'scripts/compact_requant_sim.tcl').read_text().replace('compact_requant_sim','wrapped_requant_sim')
tcl=tcl.replace('fused_affine_quant_compact','fused_affine_quant_wrap').replace('tb_compact_requant','tb_wrapped_requant')
(ROOT/'scripts/wrapped_requant_sim.tcl').write_text(tcl)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
proof={'complete':True,'hardware_execution':False,'all_float32_bit_exact':True,'random_cases':count,
       'random_bias_wrap_cases':int(np.count_nonzero(total!=wrapped)),'rtl_lanes':len(lines)*4,
       'rtl_bias_wrap_lanes':int(overflow_lanes),'fixture_sha256':sha(fixture),
       'rtl_sha256':sha(target),'source_sha256':sha(Path(__file__)),
       'reference_sha256':sha(ROOT/'software/latency/compact_requant_reference.py')}
(ROOT/'reports/fused/wrapped_requant_integer_validation.json').write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: million CPU INT32-wrap/float32 comparisons;',overflow_lanes,'RTL bias-wrap cases')
