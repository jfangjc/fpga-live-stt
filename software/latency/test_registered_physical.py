"""Kernel ownership/error checks plus independent NumPy physical block parity."""
import ctypes,errno,fcntl,json,os,struct
import numpy as np
from registered_benchmark import *

items=artifacts();library=items['library'];lib=ctypes.CDLL(str(library))
runner=make_session(items['fpga'],{'threads':1,'spin':0,'level':'extended'},[items['boundary_library'],library])
arrays={v.name:onnx.numpy_helper.to_array(v) for v in items['fpga'].graph.initializer}
programs={}
for node in items['fpga'].graph.node:
    if node.domain!='prototype.fpga.stream.registered':continue
    raw=arrays[node.input[2]].tobytes();tag=2166136261
    for b in raw:tag=((tag^b)*16777619)&0xffffffff
    programs[tag or 1]=raw
lib.fpga_stream_copy_prefix.argtypes=[ctypes.c_uint,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_uint),ctypes.POINTER(ctypes.c_uint)]
lib.fpga_stream_copy_prefix.restype=ctypes.c_int64
prefixes=[]
for i in range(23):
    n=ctypes.c_uint();tag=ctypes.c_uint()
    length=lib.fpga_stream_copy_prefix(i,None,0,ctypes.byref(n),ctypes.byref(tag))
    buf=(ctypes.c_uint8*length)();assert lib.fpga_stream_copy_prefix(i,buf,length,ctypes.byref(n),ctypes.byref(tag))==length
    prefixes.append((n.value,tag.value,bytes(buf)))

REG=(3<<30)|(32<<16)|(ord('Q')<<8)|6
RUN=(3<<30)|(40<<16)|(ord('Q')<<8)|7
FREE=(1<<30)|(8<<16)|(ord('Q')<<8)|8
checks=[]
def reject(fd,command,packet,want):
    try:fcntl.ioctl(fd,command,packet,True)
    except OSError as e:assert e.errno==want,(command,e.errno,want)
    else:raise AssertionError('Invalid request accepted')
    checks.append({'operation':command&255,'errno':want})
def register(fd,buf,flags=0,reserved=0):
    r=bytearray(struct.pack('<QQIIQ',ctypes.addressof(buf),0,len(buf)-1,flags,reserved))
    fcntl.ioctl(fd,REG,r,True);handle=struct.unpack_from('<Q',r,8)[0];assert handle
    return handle

minimal=next(p for n,tag,p in prefixes if n==1)
source=ctypes.create_string_buffer(minimal)
f1=os.open('/dev/qn-tile',os.O_RDWR);f2=os.open('/dev/qn-tile',os.O_RDWR)
try:
    handle=register(f1,source)
    valid=bytearray(struct.pack('<QQQIIII',0,0,handle,1,0,4096,4128))
    reject(f2,RUN,valid.copy(),errno.ESTALE)
    reject(f2,FREE,bytearray(struct.pack('<Q',handle)),errno.ESTALE)
    reject(f1,RUN,valid.copy(),errno.EFAULT) # Bad activation pointer; no DMA queued.
    for offset,value in ((16,0),(24,0),(24,257),(28,2),(32,4095),(36,4127)):
        bad=valid.copy();struct.pack_into('<Q' if offset==16 else '<I',bad,offset,value)
        reject(f1,RUN,bad,errno.EINVAL)
    fcntl.ioctl(f1,FREE,bytearray(struct.pack('<Q',handle)))
    reject(f1,RUN,valid,errno.ESTALE)
    reject(f1,FREE,bytearray(struct.pack('<Q',handle)),errno.ESTALE)
    for offset in (0,4,8,12,20,32+2,32+8,48+65536+4,48+65536+12,48+69632+41):
        bad=bytearray(minimal);bad[offset]^=1
        if offset==12:bad[12:16]=bytes(4)
        # Padding byte must be outside this stage's actual kernel.
        if offset==48+69632+41:bad[offset]=1
        buf=ctypes.create_string_buffer(bytes(bad))
        request=bytearray(struct.pack('<QQIIQ',ctypes.addressof(buf),0,len(minimal),0,0))
        reject(f1,REG,request,errno.EINVAL)
    for request in (struct.pack('<QQIIQ',0,0,len(minimal),0,0),
                    struct.pack('<QQIIQ',ctypes.addressof(source),1,len(minimal),0,0),
                    struct.pack('<QQIIQ',ctypes.addressof(source),0,len(minimal),1,0),
                    struct.pack('<QQIIQ',ctypes.addressof(source),0,len(minimal),0,1)):
        reject(f1,REG,bytearray(request),errno.EFAULT if struct.unpack_from('<Q',request)[0]==0 else errno.EINVAL)
    # Filling all slots twice across close/open checks both capacity and cleanup.
    for cycle in range(2):
        fd=os.open('/dev/qn-tile',os.O_RDWR)
        try:
            handles=[register(fd,source) for _ in range(64)];assert len(set(handles))==64
            request=bytearray(struct.pack('<QQIIQ',ctypes.addressof(source),0,len(minimal),0,0))
            reject(fd,REG,request,errno.ENOSPC)
        finally:os.close(fd)
finally:os.close(f1);os.close(f2)

def reference(raw,x,valid):
    count=struct.unpack_from('<I',raw,4)[0];pos=8;a=x.astype(np.int64)
    def take(dtype,n):
        nonlocal pos
        value=np.frombuffer(raw,dtype=dtype,count=n,offset=pos).copy();pos+=value.nbytes;return value
    def quant(acc,ratio,zero):
        return np.clip(np.rint(acc.astype(np.float32)*ratio[:,None]).astype(np.int64)+zero,0,255).astype(np.uint8)
    for stage in range(count):
        kernel,zx,dz,pz,sx,ds,ps=struct.unpack_from('<IIIIfff',raw,pos);pos+=28
        dwscale=take('<f4',256);pwscale=take('<f4',256);db=take('<i4',256);pb=take('<i4',256)
        dw=take('i1',256*kernel).reshape(256,kernel).astype(np.int64)
        pw=take('i1',65536).reshape(256,256).astype(np.int64);lut=take('u1',256)
        masked=struct.unpack_from('<I',raw,pos)[0];pos+=4
        t=a.shape[1];acc=np.broadcast_to(db[:,None].astype(np.int64),(256,t)).copy()
        for tap in range(kernel):
            shift=tap-kernel//2;left=max(0,-shift);right=min(t,t-shift)
            if left<right:acc[:,left:right]+=(a[:,left+shift:right+shift]-zx)*dw[:,tap,None]
        inter=quant(acc,(np.float32(sx)*dwscale)/np.float32(ds),dz);inter[:,valid:]=dz
        acc=pb[:,None].astype(np.int64)+pw@(inter.astype(np.int64)-dz)
        a=quant(acc,(np.float32(ds)*pwscale)/np.float32(ps),pz)
        if stage+1<count:a=lut[a];a[:,valid:]=masked
        a=a.astype(np.int64)
    assert pos==len(raw);return a.astype(np.uint8)

lib.qnc_open.argtypes=[ctypes.c_char_p];lib.qnc_open.restype=ctypes.c_void_p
lib.qnc_close.argtypes=[ctypes.c_void_p]
lib.qnc_register_stream.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_uint64)]
lib.qnc_release_stream.argtypes=[ctypes.c_void_p,ctypes.c_uint64]
lib.qnc_run_registered.argtypes=[ctypes.c_void_p,ctypes.c_uint64,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t,ctypes.c_void_p]
ctx=lib.qnc_open(b'/dev/qn-tile');assert ctx
rng=np.random.default_rng(20261012);cases=[]
try:
    for n,tag,prefix in prefixes:
        buffer=ctypes.create_string_buffer(prefix+bytes(65536));handle=ctypes.c_uint64()
        assert lib.qnc_register_stream(ctx,buffer,len(prefix),ctypes.byref(handle))==0
        try:
            # Userspace mutation after registration must not alter the device's
            # immutable program. This modifies an actual PW weight byte.
            buffer[32+n*16]=bytes([prefix[32+n*16]^1])
            for t in (1,17,65,256):
                for valid in (0,t//2,t):
                    x=rng.integers(0,256,(256,t),dtype=np.uint8);y=np.empty_like(x)
                    expected=reference(programs[tag],x,valid)
                    assert lib.qnc_run_registered(ctx,handle.value,buffer,len(prefix),len(buffer),n,tag,x.ctypes.data,t,valid,y.ctypes.data)==0
                    np.testing.assert_array_equal(y,expected)
                    cases.append({'stages':n,'tag':tag,'times':t,'valid_times':valid,'numpy_bit_exact':True})
        finally:assert lib.qnc_release_stream(ctx,handle.value)==0
        print('PASS registered physical program',tag,'stages',n,flush=True)
finally:lib.qnc_close(ctx)
write_json(ROOT/'reports/fused/registered_physical_packets.json',bindings(items)|{
    'complete':True,'all_numpy_bit_exact':True,'immutable_program_tested':True,'fd_close_cleanup_tested':True,
    'kernel_rejections':checks,'physical_cases':cases,'source_sha256':sha(__file__)})
print('PASS:',len(cases),'independent NumPy physical blocks;',len(checks),'kernel rejections and FD cleanup',flush=True)
