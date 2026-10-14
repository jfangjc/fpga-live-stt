"""Independent integer fixtures for the unchanged 72-case primitive RTL test.

Move expensive testbench reference loops to NumPy; hardware simulation still
executes every original packet, counter, protocol and output-byte assertion.
"""
import hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];dest=ROOT/'verification/chain-prefetch-vectors';dest.mkdir(parents=True,exist_ok=True)
def requant(total,zero):
    q=np.floor_divide(total,128);r=total-q*128
    return np.clip(q+((r>64)|((r==64)&((q&1)!=0)))+zero,0,255).astype(np.int64)
def pair(x,t,v,seed,kernel,zx,dzy,pzy):
    padded=(t+15)//16*16;c=np.arange(256,dtype=np.int64)
    mid=np.empty((256,padded),np.int64)
    total=np.broadcast_to((c*3-57)[:,None],mid.shape).copy()
    for d in range(kernel):
        idx=np.arange(padded)+d-kernel//2;valid=(idx>=0)&(idx<t)
        w=(d*31+c*13+seed*3)%256-128
        total[:,valid]+=w[:,None]*(x[:,idx[valid]]-zx)
    mid=requant(total,dzy);mid[:,v:]=dzy
    w=(c[:,None]*31+c[None,:]*13+seed*3)%256-128
    total=w.T@(mid-dzy)+(c*57-231)[:,None]
    return requant(total,pzy)
def ordered(y):
    return y.reshape(16,16,y.shape[1]//16,16).transpose(2,0,3,1).reshape(-1)
def write(name,y):
    path=dest/name;path.write_text(''.join(f'{int(v):02x}\n' for v in ordered(y)))
def initial(t,seed):return (np.arange(256)[:,None]*17+np.arange(t)[None,:]*7+seed)%256
for t,v,n in ((1,1,1),(17,13,2),(51,51,3),(101,99,5),(256,255,3),(65,0,2)):
    x=initial(t,11)
    for stage in range(n):
        ss=stage%3
        y=pair(x,t,v,(11,16,26)[ss],(11,13,17)[ss],(128,145,179)[ss],(127,110,76)[ss],(128,141,167)[ss])
        if stage<n-1:
            x=(y[:,:t]*3+stage*7)%256;x[:,v:]=17+stage*10
    write(f'chain_{t}_{v}_{n}.mem',y)
cases=[(17,13,11+i*5,11+2*i,128+17*i,127-17*i,128+13*i) for i in range(6)]
cases += [(51,51,11,11,128,127,128),(101,99,26,17,179,76,167),(256,255,26,17,179,76,167),
          (17,0,16,13,145,110,141),(17,13,44,17,220,37,129),(17,13,11,15,128,127,128)]
for t,v,seed,kernel,zx,dzy,pzy in cases:
    write(f'pair_{t}_{v}_{seed}_{kernel}_{zx}_{dzy}_{pzy}.mem',pair(initial(t,seed),t,v,seed,kernel,zx,dzy,pzy))
text=(ROOT/'sim/tb_qn_chain_axis.sv').read_text().replace('module tb_qn_chain_axis;','module tb_qn_chain_prefetch_vectors;')
start=text.index('   for(c=0;c<256;c=c+1)for(p=0;p<t;p=p+1)chain_x')
end=text.index('   expected_mac=n*nt*8*256;',start)
text=text[:start]+f'''   $readmemh($sformatf("{dest.as_posix()}/chain_%0d_%0d_%0d.mem",t,v,n),expected,0,nt*16*16*16-1);
'''+text[end:]
start=text.index('   for(i=0;i<k;i=i+1)for(p=0;p<nt*16;p=p+1)begin',text.index(' task pair_case'))
end=text.index('   expected_mac=nt*((groups+1)/2)*k;',start)
text=text[:start]+f'''   $readmemh($sformatf("{dest.as_posix()}/pair_%0d_%0d_%0d_%0d_%0d_%0d_%0d.mem",t,v,seed,test_kernel,zx,dzy,pzy),expected,0,nt*groups*16*16-1);
'''+text[end:]
(ROOT/'sim/tb_qn_chain_prefetch_vectors.sv').write_text(text)
script=(ROOT/'scripts/chain_prefetch_sim.tcl').read_text().replace('chain_prefetch_sim','chain_prefetch_vector_sim').replace('tb_qn_chain_axis','tb_qn_chain_prefetch_vectors')
(ROOT/'scripts/chain_prefetch_vector_sim.tcl').write_text(script)
manifest={'independent_reference':True,'arithmetic':'Integer floor/remainder ties-to-even; explicit DW padding/masking and pointwise matmul',
          'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'files_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(dest.glob('*.mem'))}}
(dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Generated',len(manifest['files_sha256']),'independent fixtures; all 72 hardware cases retained')
