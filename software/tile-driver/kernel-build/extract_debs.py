from pathlib import Path
import tarfile,io
root=Path(__file__).parent; target=root/'sysroot'; target.mkdir(exist_ok=True)
import sys
for p in [root/n for n in sys.argv[1:]] if len(sys.argv)>1 else root.glob('*.deb'):
 d=p.read_bytes(); off=8
 while off<len(d):
  hdr=d[off:off+60]; n=int(hdr[48:58]); name=hdr[:16].decode().strip().rstrip('/'); b=d[off+60:off+60+n]; off+=60+n+(n%2)
  if name.startswith('data.tar'):
   with tarfile.open(fileobj=io.BytesIO(b)) as t:
    for m in t:
     try: t.extract(m,target,filter='data')
     except tarfile.FilterError as e: print('SKIPPED',m.name,str(e))
 print('extracted',p.name)

