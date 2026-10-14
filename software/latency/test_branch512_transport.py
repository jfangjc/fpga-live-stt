"""Independent model-prefix and two-output packet checks through mock callbacks."""
import ctypes,json,struct,sys
from pathlib import Path
import numpy as np
from tail_benchmark import *
sys.path.insert(0,str(ROOT/'software/ort_fpga_stream_branch512'))
from branch_graph import compile_branches
from pair_graph import candidate as pairs
model=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
graph,records,bounds=compile_branches(transform(pairs(model,False)[0])[0]);graph,_=tails(graph)
library=ROOT/'software/ort_fpga_stream_branch512/libort_fpga.so';lib=ctypes.CDLL(str(library))
runner=make_session(graph,{'threads':1,'spin':0,'level':'extended'},[ROOT/'software/latency/libboundary_lut.so',library])
lib.fpga_stream_prefix_count.restype=ctypes.c_size_t
lib.fpga_stream_copy_prefix.argtypes=[ctypes.c_uint,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_uint),ctypes.POINTER(ctypes.c_uint)]
lib.fpga_stream_copy_prefix.restype=ctypes.c_int64
arrays={v.name:onnx.numpy_helper.to_array(v) for v in graph.graph.initializer}
parent=ROOT/'software/latency/test_registered_transport.py';text=parent.read_text()
function=text[text.index('def construct(raw):'):text.index('\nexpected={}')] 
function=function.replace('def construct(raw):','def construct(raw,branch):')
function=function.replace('17|(256<<16)','(18 if branch else 17)|(256<<16)')
function=function.replace('        assert np.all(correction>=-(1<<31))',
    '        if branch and i==0:correction=(correction+(1<<31))%(1<<32)-(1<<31)\n        assert np.all(correction>=-(1<<31))')
exec(function)
expected={}
for node in graph.graph.node:
    if node.domain!='prototype.fpga.stream.branch512':continue
    assert node.op_type in ('FpgaBranch','FpgaChain')
    branch=node.op_type=='FpgaBranch';attrs={a.name:onnx.helper.get_attribute_value(a) for a in node.attribute}
    stride=attrs.get('residual_stride',1)
    tag,n,prefix=construct(arrays[node.input[2]].tobytes(),branch)
    assert tag not in expected;expected[tag]=(n,prefix,branch,stride)
assert len(expected)==lib.fpga_stream_prefix_count()==23
prefixes=[]
for i in range(23):
    n=ctypes.c_uint();tag=ctypes.c_uint();length=lib.fpga_stream_copy_prefix(i,None,0,ctypes.byref(n),ctypes.byref(tag))
    buf=(ctypes.c_uint8*length)();assert lib.fpga_stream_copy_prefix(i,buf,length,ctypes.byref(n),ctypes.byref(tag))==length
    count,prefix,branch,stride=expected[tag.value];assert (n.value,bytes(buf))==(count,prefix)
    prefixes.append((count,tag.value,prefix,branch,stride))
callback_type=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_int)
state={};errors=[];checks=[];rng=np.random.default_rng(2026101244)
def values(n,padded,residual=False):
    return ((np.arange(256)[:,None]*(11 if residual else 17)+np.arange(padded)[None,:]*(13 if residual else 7)+n*(5 if residual else 3))%256).astype(np.uint8)
def exchange(_,tx,rx,a,b,count,batch):
    try:
        n,tag,prefix,branch,stride=state['prefix'];t=state['t'];valid=state['valid'];x=state['x'];padded=((t+15)//16)*16
        assert count==1 and batch==0 and a==len(prefix)+256*padded and b==(48+512*padded if branch else 32+256*padded)
        packet=ctypes.string_at(tx,a);reference=bytearray(prefix)
        struct.pack_into('<I',reference,8,256|(t<<16));struct.pack_into('<I',reference,16,valid|(n<<16))
        assert packet[:len(prefix)]==reference
        packed=np.frombuffer(packet[len(prefix):],np.uint8).reshape(256,padded)
        np.testing.assert_array_equal(packed[:,:t],x);assert not np.any(packed[:,t:])
        error=state['error']
        if error=='dma':return -5
        response=bytearray(b)
        def ack(offset,second=False):
            struct.pack_into('<IIII',response,offset,0x32524e51,
                1 if error==('branch_status' if second else 'status') else 0,
                (256|(256<<16))^(1 if second and error=='branch_shape' else 0),
                tag^(1 if error==('branch_tag' if second else 'tag') else 0))
        def payload(offset,residual):
            response[offset:offset+256*padded]=values(n,padded,residual).reshape(16,16,padded//16,16).transpose(2,0,3,1).tobytes()
        ack(0);payload(16,branch)
        if branch:ack(16+256*padded,True);payload(32+256*padded,False)
        issues=n*(padded//16)*2048
        struct.pack_into('<IIII',response,b-16,issues+(1 if error=='counter' else 0),0,0,issues+10000)
        ctypes.memmove(rx,bytes(response),b);return 0
    except Exception as e:errors.append(repr(e));return -22
callback=callback_type(exchange)
lib.qnc_create.argtypes=[callback_type,ctypes.c_void_p];lib.qnc_create.restype=ctypes.c_void_p
lib.qnc_close.argtypes=[ctypes.c_void_p]
common_types=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t,ctypes.c_void_p]
lib.qnc_run_stream_reuse.argtypes=common_types
lib.qnc_run_branch_reuse.argtypes=common_types+[ctypes.c_void_p,ctypes.c_uint]
error_checks=0
for item in prefixes:
    n,tag,prefix,branch,stride=item;ctx=lib.qnc_create(callback,None);assert ctx
    try:
        reusable=ctypes.create_string_buffer(prefix+bytes(65536))
        for t in (1,17,65,256):
            for valid in (0,t//2,t):
                x=rng.integers(0,256,(256,t),dtype=np.uint8);y=np.zeros_like(x);res=np.zeros((256,(t+stride-1)//stride),np.uint8)
                state={'prefix':item,'t':t,'valid':valid,'x':x,'error':None}
                def run():
                    args=(ctx,reusable,len(prefix),len(reusable),n,tag,x.ctypes.data,t,valid,y.ctypes.data)
                    return lib.qnc_run_branch_reuse(*args,res.ctypes.data,stride) if branch else lib.qnc_run_stream_reuse(*args)
                assert run()==0 and not errors,errors
                np.testing.assert_array_equal(y,values(n,t))
                if branch:np.testing.assert_array_equal(res,values(n,t,True)[:,::stride])
                checks.append({'tag':tag,'branch':branch,'stride':stride,'t':t,'valid':valid,'packet_and_outputs_exact':True})
        for error in ('dma','status','tag','counter')+(('branch_status','branch_tag','branch_shape') if branch else ()):
            state['error']=error;assert run()<0 and not errors;error_checks+=1
    finally:lib.qnc_close(ctx)
write_json(ROOT/'reports/fused/branch512_mock_transport.json',{'complete':True,'hardware_execution':False,
    'all_model_prefixes_independently_exact':True,'prefixes':23,'branches':21,'packet_checks':len(checks),
    'error_checks':error_checks,'checks':checks,'library_sha256':sha(library),
    'runtime_source_sha256':sha(ROOT/'software/ort_fpga_stream_branch512/pointwise.cc'),
    'transport_source_sha256':sha(ROOT/'software/ort_fpga_stream_branch512/qnc_transport.c'),
    'source_sha256':sha(__file__),'parent_prefix_constructor_sha256':sha(parent)})
print('PASS:',len(checks),'independent packet/two-output checks and',error_checks,'transport rejections',flush=True)
