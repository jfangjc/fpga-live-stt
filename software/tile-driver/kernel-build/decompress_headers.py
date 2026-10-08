from pathlib import Path
import compression.zstd
root=Path(__file__).parent
for p in root.glob('linux*.deb'):
 d=p.read_bytes(); off=8
 while off<len(d):
  hdr=d[off:off+60]; n=int(hdr[48:58]); name=hdr[:16].decode().strip().rstrip('/'); b=d[off+60:off+60+n]; off+=60+n+(n%2)
  if name=='data.tar.zst':
   (root/(p.stem+'.tar')).write_bytes(compression.zstd.decompress(b)); print(p.name,flush=True)
