"""Integer specification of ARM float32 requantization, including double rounding."""
import numpy as np

def msb(values):
    tmp=np.asarray(values,np.uint64).copy();bits=np.zeros(tmp.shape,np.uint64)
    for step in (32,16,8,4,2,1):
        upper=tmp>>np.uint64(step);yes=upper!=0;bits+=yes.astype(np.uint64)*step;tmp=np.where(yes,upper,tmp)
    return bits

def round_significand(values):
    values=np.asarray(values,np.uint64);leading=msb(values);drop=np.where(leading>23,leading-23,0).astype(np.uint64)
    quotient=values>>drop;mask=(np.uint64(1)<<drop)-np.uint64(1);remainder=values&mask
    half=np.uint64(1)<<np.where(drop>0,drop-1,0).astype(np.uint64)
    quotient+=((drop>0)&((remainder>half)|((remainder==half)&((quotient&1)!=0)))).astype(np.uint64)
    return quotient<<drop

def requant(acc,multiplier,shift,zero):
    acc=np.asarray(acc,np.int64);multiplier=np.asarray(multiplier,np.uint64);shift=np.asarray(shift,np.uint64)
    magnitude=round_significand(np.abs(acc).astype(np.uint64));product=round_significand(magnitude*multiplier)
    q=product>>shift;remainder=product&((np.uint64(1)<<shift)-np.uint64(1));half=np.uint64(1)<<(shift-1)
    q+=((remainder>half)|((remainder==half)&((q&1)!=0))).astype(np.uint64)
    signed=np.where(acc<0,-q.astype(np.int64),q.astype(np.int64))
    return np.clip(signed+np.asarray(zero,np.int64),0,255).astype(np.uint8)
