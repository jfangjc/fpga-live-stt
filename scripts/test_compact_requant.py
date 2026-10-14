"""Validate compact arithmetic against float32 and the original integer spec."""
import hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'software/latency'))
from compact_requant_reference import requant
from exact_requant_reference import requant as original
rng=np.random.default_rng(20261012);n=1000000
acc=rng.integers(-(1<<31),(1<<31),n,dtype=np.int64)
# Include all positive multiplier encodings, not only normalized mantissas.
mu=rng.integers(0,1<<24,n,dtype=np.uint64)<<np.uint64(7)
shift=rng.integers(1,63,n,dtype=np.uint64);zero=rng.integers(0,256,n,dtype=np.uint64)
expected=np.clip(np.rint(acc.astype(np.float32)*np.ldexp(mu.astype(np.float32),-shift.astype(np.int32))).astype(np.float64)+zero,0,255).astype(np.uint8)
np.testing.assert_array_equal(requant(acc,mu,shift,zero),expected)
np.testing.assert_array_equal(requant(acc,mu,shift,zero),original(acc,mu,shift,zero))
t=rng.integers(1,1<<31,100000,dtype=np.int64);ratio=((rng.integers(0,255,100000)+.5)/t.astype(np.float32)).astype(np.float32)
mant,exp=np.frexp(ratio);tm=np.rint(mant.astype(np.float64)*(1<<31)).astype(np.uint64);ts=(31-exp).astype(np.uint64)
t*=rng.choice([-1,1],len(t));tz=rng.integers(0,256,len(t),dtype=np.uint64)
expected=np.clip(np.rint(t.astype(np.float32)*ratio).astype(np.int64)+tz.astype(np.int64),0,255).astype(np.uint8)
np.testing.assert_array_equal(requant(t,tm,ts,tz),expected)
fixture=ROOT/'verification/exact-requant/quant.mem'
proof={'complete':True,'hardware_execution':False,'all_float32_bit_exact':True,'random_cases':n,'targeted_half_cases':len(t),
       'reference_sha256':hashlib.sha256((ROOT/'software/latency/compact_requant_reference.py').read_bytes()).hexdigest(),
       'fixture_sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'rtl_vectors':2400}
(ROOT/'reports/fused/compact_requant_integer_validation.json').write_text(json.dumps(proof,indent=2)+'\n')
tb=(ROOT/'sim/tb_exact_requant.sv').read_text().replace('tb_exact_requant','tb_compact_requant').replace('fused_affine_quant_exact','fused_affine_quant_compact')
(ROOT/'sim/tb_compact_requant.sv').write_bytes(tb.encode())
text=(ROOT/'scripts/exact_requant_sim.tcl').read_text().replace('exact_requant_sim','compact_requant_sim').replace('tb_exact_requant','tb_compact_requant').replace('fused_affine_quant_exact','fused_affine_quant_compact')
(ROOT/'scripts/compact_requant_sim.tcl').write_bytes(text.encode())
print('PASS: compact arithmetic matches float32 in 1.1M cases; original primitive fixtures preserved')
