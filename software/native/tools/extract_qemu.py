"""Extract one verified emulator only; never install packages or register binfmt."""
import ctypes
import hashlib
import io
from pathlib import Path
import tarfile
root=Path(__file__).parent
package=(root/'qemu-user-static.deb').read_bytes()
assert hashlib.sha256(package).hexdigest()=='a8f4e6121b7d1710885ba00fdb1e5a8256fb396f12ade2da9ed8a3693ad6d1bd'
assert package[:8]==b'!<arch>\n'
pos=8
while pos<len(package):
    header=package[pos:pos+60];size=int(header[48:58]);name=header[:16].decode().strip()
    if name=='data.tar.zst': compressed=package[pos+60:pos+60+size];break
    pos+=60+size+(size%2)
else: raise ValueError('Missing data archive')
lib=ctypes.CDLL('libzstd.so.1')
lib.ZSTD_getFrameContentSize.argtypes=[ctypes.c_void_p,ctypes.c_size_t];lib.ZSTD_getFrameContentSize.restype=ctypes.c_uint64
size=lib.ZSTD_getFrameContentSize(compressed,len(compressed))
if size>=2**64-2:
    lib.ZSTD_decompressBound.argtypes=[ctypes.c_void_p,ctypes.c_size_t];lib.ZSTD_decompressBound.restype=ctypes.c_uint64
    size=lib.ZSTD_decompressBound(compressed,len(compressed))
assert 0<size<512_000_000,size
dest=ctypes.create_string_buffer(size)
lib.ZSTD_decompress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t];lib.ZSTD_decompress.restype=ctypes.c_size_t
actual=lib.ZSTD_decompress(dest,size,compressed,len(compressed));assert 0<actual<=size
with tarfile.open(fileobj=io.BytesIO(dest.raw[:actual]),mode='r:') as archive:
    member=archive.getmember('./usr/bin/qemu-aarch64-static');assert member.isfile()
    data=archive.extractfile(member).read()
out=root/'qemu-aarch64-static';out.write_bytes(data);out.chmod(0o755)
print(hashlib.sha256(data).hexdigest())
