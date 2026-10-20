"""Exact 24-bit significand specification; cap after both float rounding steps."""
import numpy as np
from exact_requant_reference import msb
def normalized(values):
    values=np.asarray(values,np.uint64);bits=msb(values)
    drops=np.where(bits>23,bits-23,0).astype(np.uint64)
    q=values>>drops;rem=values&((np.uint64(1)<<drops)-np.uint64(1))
    half=np.uint64(1)<<np.where(drops>0,drops-1,0).astype(np.uint64)
    q+=((drops>0)&((rem>half)|((rem==half)&((q&1)!=0)))).astype(np.uint64)
    carry=q>=np.uint64(1<<24);q=np.where(carry,np.uint64(1<<23),q);drops+=carry.astype(np.uint64)
    return q,drops
def requant(acc,multiplier,shift,zero):
    acc=np.asarray(acc,np.int64);multiplier=np.asarray(multiplier,np.uint64);shift=np.asarray(shift,np.int64)
    a,ad=normalized(np.abs(acc));p,pd=normalized(a*(multiplier>>np.uint64(7)))
    effective=shift-ad.astype(np.int64)-7-pd.astype(np.int64)
    right=np.clip(effective,1,24).astype(np.uint64);q=p>>right
    rem=p&((np.uint64(1)<<right)-np.uint64(1));half=np.uint64(1)<<(right-1)
    q+=((rem>half)|((rem==half)&((q&1)!=0))).astype(np.uint64)
    left=np.clip(-effective,0,8).astype(np.uint64)
    magnitude=np.where(effective>24,0,np.where(effective>0,q,p<<left))
    magnitude=np.minimum(magnitude,256).astype(np.int64)
    return np.clip(np.where(acc<0,-magnitude,magnitude)+np.asarray(zero,np.int64),0,255).astype(np.uint8)
