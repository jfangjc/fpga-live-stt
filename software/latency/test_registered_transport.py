"""Independent prefix construction and explicit mock transport; no FPGA execution."""
import ctypes,gc,json,struct,sys
from pathlib import Path
import numpy as np
from tail_benchmark import *
sys.path.insert(0,str(ROOT/'software/ort_fpga_stream_registered'))
from pair_graph import candidate as pairs
from stream_graph import compile_chains
model=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx');pair,selection=pairs(model,False)
graph,groups=compile_chains(transform(pair)[0]);graph,_=tails(graph)
library=ROOT/'software/ort_fpga_stream_registered/libort_fpga.so';lib=ctypes.CDLL(str(library))
runner=make_session(graph,{'threads':1,'spin':0,'level':'extended'},[ROOT/'software/latency/libboundary_lut.so',library])
lib.fpga_stream_prefix_count.restype=ctypes.c_size_t
lib.fpga_stream_copy_prefix.argtypes=[ctypes.c_uint,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_uint),ctypes.POINTER(ctypes.c_uint)]
lib.fpga_stream_copy_prefix.restype=ctypes.c_int64
arrays={v.name:onnx.numpy_helper.to_array(v) for v in graph.graph.initializer}

def construct(raw):
    count=struct.unpack_from('<I',raw,4)[0];pos=8;stages=[]
    def take(dtype,n):
        nonlocal pos
        arr=np.frombuffer(raw,dtype=dtype,count=n,offset=pos).copy();pos+=arr.nbytes;return arr
    def quant(sx,sw,sy):
        ratio=(np.float32(sx)*sw)/np.float32(sy);mant,exp=np.frexp(ratio)
        mult=np.rint(mant.astype(np.float64)*(1<<31)).astype(np.int64);shift=31-exp
        tiny=ratio<=np.float32(2**-32);mult[tiny]=0;shift[tiny]=1
        return mult,shift
    for i in range(count):
        kernel,zx,dz,pz,sx,ds,ps=struct.unpack_from('<IIIIfff',raw,pos);pos+=28
        dwscale=take('<f4',256);pwscale=take('<f4',256);db=take('<i4',256);pb=take('<i4',256)
        dw=take('i1',256*kernel).reshape(256,kernel);pw=take('i1',65536).reshape(256,256);lut=take('u1',256)
        masked=struct.unpack_from('<I',raw,pos)[0];pos+=4
        dm,dshift=quant(sx,dwscale,ds);pm,pshift=quant(ds,pwscale,ps)
        stages.append((kernel,zx,dz,pz,db,pb,dw,pw,lut,masked,dm,dshift,pm,pshift))
    assert pos==len(raw)
    tag=2166136261
    for value in raw:tag=((tag^value)*16777619)&0xffffffff
    tag=tag or 1;out=bytearray(32+count*16+count*86016+(count-1)*256)
    struct.pack_into('<IIII',out,0,0x32434e51,17|(256<<16),256,tag);struct.pack_into('<I',out,16,count<<16)
    for i,(kernel,zx,dz,pz,db,pb,dw,pw,lut,masked,dm,dshift,pm,pshift) in enumerate(stages):
        stag=(tag+i*0x9e3779b9)&0xffffffff;stag=stag or 1
        struct.pack_into('<II',out,32+i*16,i|(masked<<8)|(kernel<<16),stag)
        base=32+count*16+i*86016
        out[base:base+65536]=pw.reshape(16,16,256).transpose(0,2,1).tobytes()
        correction=pb.astype(np.int64)+(128-dz)*pw.astype(np.int64).sum(1)
        assert np.all(correction>=-(1<<31)) and np.all(correction<(1<<31))
        for c in range(256):
            struct.pack_into('<iiII',out,base+65536+c*16,int(correction[c]),int(pm[c]),int(pshift[c])|(pz<<8),0)
            out[base+69632+c*48:base+69632+c*48+kernel]=dw[c].tobytes()
            struct.pack_into('<iiII',out,base+81920+c*16,int(db[c]),int(dm[c]),int(dshift[c])|(dz<<8),zx)
        if i+1<count:out[32+count*16+count*86016+i*256:32+count*16+count*86016+(i+1)*256]=lut.tobytes()
    return tag,count,bytes(out)

expected={}
for node in graph.graph.node:
    if node.domain=='prototype.fpga.stream.registered' and node.op_type=='FpgaChain':
        tag,n,prefix=construct(arrays[node.input[2]].tobytes());assert tag not in expected;expected[tag]=(n,prefix)
assert len(expected)==23 and lib.fpga_stream_prefix_count()==23
prefixes=[]
for i in range(23):
    n=ctypes.c_uint();tag=ctypes.c_uint();length=lib.fpga_stream_copy_prefix(i,None,0,ctypes.byref(n),ctypes.byref(tag))
    buf=(ctypes.c_uint8*length)();assert lib.fpga_stream_copy_prefix(i,buf,length,ctypes.byref(n),ctypes.byref(tag))==length
    assert expected[tag.value]==(n.value,bytes(buf));prefixes.append((n.value,tag.value,bytes(buf)))

callback_type=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_int)
state={};errors=[];checks=[];rng=np.random.default_rng(20261012)
def exchange(_,tx,rx,a,b,count,batch):
    try:
        packet=ctypes.string_at(tx,a);n,tag,prefix=state['prefix'];t=state['t'];valid=state['valid'];x=state['x'];tiles=(t+15)//16;padded=tiles*16
        assert count==1 and batch==0 and a==len(prefix)+256*padded and b==32+tiles*4096
        reference=bytearray(prefix);struct.pack_into('<I',reference,8,256|(t<<16));struct.pack_into('<I',reference,16,valid|(n<<16))
        assert packet[:len(prefix)]==reference
        packed=np.frombuffer(packet[len(prefix):],np.uint8).reshape(256,padded)
        np.testing.assert_array_equal(packed[:,:t],x);assert not np.any(packed[:,t:])
        if state['error']=='dma':return -5
        response=bytearray(b);struct.pack_into('<IIII',response,0,0x32524e51,1 if state['error']=='status' else 0,
                                           256|(256<<16),tag^1 if state['error']=='tag' else tag)
        values=((np.arange(256)[:,None]*17+np.arange(padded)[None,:]*7+n*3)%256).astype(np.uint8)
        response[16:b-16]=values.reshape(16,16,tiles,16).transpose(2,0,3,1).tobytes()
        issues=n*tiles*2048;struct.pack_into('<IIII',response,b-16,issues+(1 if state['error']=='counter' else 0),0,0,issues+10000)
        ctypes.memmove(rx,bytes(response),b);return 0
    except Exception as e:errors.append(repr(e));return -22
callback=callback_type(exchange)
lib.qnc_create.argtypes=[callback_type,ctypes.c_void_p];lib.qnc_create.restype=ctypes.c_void_p
lib.qnc_close.argtypes=[ctypes.c_void_p]
lib.qnc_run_stream.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t,ctypes.c_void_p]
lib.qnc_run_stream_reuse.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t,ctypes.c_void_p]
for n,tag,prefix in prefixes:
    ctx=lib.qnc_create(callback,None);assert ctx
    try:
        buffer=ctypes.create_string_buffer(prefix);reusable=ctypes.create_string_buffer(prefix+bytes(65536))
        for t in (1,17,65,256):
            for valid in (0,t//2,t):
                x=rng.integers(0,256,(256,t),dtype=np.uint8);y=np.empty_like(x)
                state={'prefix':(n,tag,prefix),'t':t,'valid':valid,'x':x,'error':None}
                rc=lib.qnc_run_stream(ctx,buffer,len(prefix),n,tag,x.ctypes.data,t,valid,y.ctypes.data)
                assert rc==0 and not errors,(rc,errors)
                expect=((np.arange(256)[:,None]*17+np.arange(t)[None,:]*7+n*3)%256).astype(np.uint8);np.testing.assert_array_equal(y,expect)
                y[:]=0
                rc=lib.qnc_run_stream_reuse(ctx,reusable,len(prefix),len(reusable),n,tag,x.ctypes.data,t,valid,y.ctypes.data)
                assert rc==0 and not errors;np.testing.assert_array_equal(y,expect)
                checks.append({'stages':n,'tag':tag,'times':t,'valid_times':valid,'mock_transport_bit_exact':True})
        for error in ('dma','status','tag','counter'):
            state['error']=error;rc=lib.qnc_run_stream(ctx,buffer,len(prefix),n,tag,x.ctypes.data,t,valid,y.ctypes.data)
            assert rc<0 and not errors,(error,rc,errors)
    finally:lib.qnc_close(ctx)
write_json(ROOT/'reports/fused/registered_mock_transport.json',{'complete':True,'hardware_execution':False,'prefixes':23,'retained_pairs':100,
           'all_model_prefixes_independently_exact':True,'packet_checks':len(checks)*2,'error_checks':23*4,'cases':checks,
           'library_sha256':sha(library),'source_sha256':sha(__file__),'transport_source_sha256':sha(ROOT/'software/ort_fpga_stream_registered/qnc_transport.c'),
           'runtime_source_sha256':sha(ROOT/'software/ort_fpga_stream_registered/pointwise.cc'),'note':'Physical graph constructors only; explicit qnc_create mock callback, no device open or FPGA graph execution'})
print('PASS: 23 model weight programs,',len(checks),'mock packets,',23*4,'propagated errors; no FPGA execution')
