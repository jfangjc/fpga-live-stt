"""Screen physical in-graph FPGA offload against the actual CPU INT8 graph."""
import argparse
import ctypes
import json
from pathlib import Path
import random
import sys
import time
import numpy as np
import onnx
from onnx import helper,numpy_helper
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
from common import Frontend,read_audio,decode,environment,sha,write_json,identity


def candidate(model,names,oracle=False,quant=False):
    # Infer standard operator outputs before replacing them: otherwise the
    # custom boundary loses known channel/rank information used by ORT.
    graph=onnx.shape_inference.infer_shapes(model)
    arrays={v.name:numpy_helper.to_array(v) for v in graph.graph.initializer}
    replaced=[]
    for node in graph.graph.node:
        if node.name not in names:continue
        attrs={a.name:helper.get_attribute_value(a) for a in node.attribute}
        w=arrays[node.input[3]]
        if(node.op_type!='QLinearConv' or w.ndim!=3 or w.shape[2]!=1 or
           attrs.get('group',1)!=1 or any(attrs.get('pads',[0,0])) or
           attrs.get('dilations',[1])!=[1] or max(w.shape[:2])>1024 or
           (quant and attrs.get('strides',[1])!=[1])):
            raise ValueError('Unsupported selected pointwise: '+node.name)
        if len(node.input)==8:
            bias=node.name+'_zero_bias'
            graph.graph.initializer.append(numpy_helper.from_array(np.zeros(w.shape[0],np.int32),bias))
            node.input.append(bias)
        if any(name not in arrays and name!=node.name+'_zero_bias' for name in node.input[1:]):
            raise ValueError('Only constant weights/quantization/bias are supported')
        del node.attribute[:]
        node.attribute.append(helper.make_attribute('stride',attrs.get('strides',[1])[0]))
        node.domain='prototype.fpga'
        node.op_type=('OracleQuadPointwise' if oracle else 'FpgaQuadPointwise') if quant else ('OraclePointwise' if oracle else 'FpgaPointwise')
        replaced.append(node.name)
    if set(replaced)!=set(names):raise ValueError('Selected node not found')
    graph.opset_import.append(helper.make_opsetid('prototype.fpga',1))
    onnx.checker.check_model(graph)
    return graph


def session(model,library=None,profile=False,threads=4):
    # Give CPU and FPGA graphs the same standard ONNX shape-inference pass.
    model=onnx.shape_inference.infer_shapes(model)
    opt=ort.SessionOptions();opt.intra_op_num_threads=threads;opt.inter_op_num_threads=1
    opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
    opt.add_session_config_entry('session.intra_op.allow_spinning','0')
    opt.add_session_config_entry('session.inter_op.allow_spinning','0')
    opt.enable_profiling=profile
    if library:opt.register_custom_ops_library(str(library.resolve()))
    return ort.InferenceSession(model.SerializeToString(),opt,providers=['CPUExecutionProvider'])


class Stats(ctypes.Structure):
    _fields_=[('ioctls',ctypes.c_uint64),('loads',ctypes.c_uint64),('runs',ctypes.c_uint64),
              ('tx_bytes',ctypes.c_uint64),('rx_bytes',ctypes.c_uint64),('ioctl_seconds',ctypes.c_double)]

class Profile(ctypes.Structure):
    _fields_=[(name,ctypes.c_double) for name in
              ('load_pack_seconds','scan_seconds','run_pack_seconds','unpack_seconds')]+[
              (name,ctypes.c_uint64) for name in ('mac_issue_cycles','input_stall_cycles','output_stall_cycles','active_cycles')]


def stats(lib):
    state=Stats();physical=ctypes.c_uint64();oracle=ctypes.c_uint64()
    lib.fpga_ort_stats(ctypes.byref(state),ctypes.byref(physical),ctypes.byref(oracle))
    profile=Profile();lib.fpga_ort_profile(ctypes.byref(profile))
    return {name:getattr(state,name) for name,_ in state._fields_}|{'physical_calls':physical.value,'oracle_calls':oracle.value}|{
        name:getattr(profile,name) for name,_ in profile._fields_}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,default=ROOT/'research/fused/cpu-int8.onnx')
    p.add_argument('--model-dir',type=Path,default=ROOT/'research/export/citrinet-256-ls')
    p.add_argument('--library',type=Path,default=Path(__file__).with_name('libort_fpga.so'))
    p.add_argument('--wav',type=Path,default=ROOT/'research/eval/user-recording/speech.wav')
    p.add_argument('--nodes',nargs='*')
    p.add_argument('--top',type=int,default=8)
    p.add_argument('--runs',type=int,default=10)
    p.add_argument('--quant',action='store_true')
    p.add_argument('--reload-weights',action='store_true',help='Include a real LOAD on every measured FPGA call')
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();args.out.parent.mkdir(parents=True,exist_ok=True)
    proof=json.loads(args.model.with_suffix('.json').read_text())
    if proof['model_sha256']!=sha(args.model) or proof['source_identity']!=identity(args.model_dir):
        raise ValueError('Candidate identity mismatch')
    model=onnx.load(str(args.model));frontend=Frontend(args.model_dir)
    vocab=(args.model_dir/'vocab.txt').read_text().splitlines()
    features,lengths=frontend(read_audio(args.wav));feed={'features':features,'feature_lengths':lengths}
    prof=session(model,profile=True)
    for _ in range(5):prof.run(None,feed)
    trace=Path(prof.end_profiling());events=json.loads(trace.read_text());del prof
    arrays={v.name:numpy_helper.to_array(v) for v in model.graph.initializer}
    eligible=[]
    for node in model.graph.node:
        if node.op_type!='QLinearConv':continue
        attrs={a.name:helper.get_attribute_value(a) for a in node.attribute}
        w=arrays[node.input[3]]
        if (w.ndim!=3 or w.shape[-1]!=1 or max(w.shape[:2])>1024 or
            attrs.get('group',1)!=1 or any(attrs.get('pads',[0,0])) or
            attrs.get('dilations',[1])!=[1] or
            (args.quant and attrs.get('strides',[1])!=[1])):continue
        eligible.append(node)
    ranking=[]
    for node in eligible:
        duration=sum(e.get('dur',0) for e in events if e.get('cat')=='Node' and
                     e.get('name','').startswith(node.name+'_') and
                     e.get('args',{}).get('op_name')=='QLinearConv')/5
        ranking.append({'node':node.name,'cpu_profile_us':duration,'weight_shape':list(arrays[node.input[3]].shape)})
    ranking.sort(key=lambda r:r['cpu_profile_us'],reverse=True)
    names=args.nodes if args.nodes else [r['node'] for r in ranking[:args.top]]
    baseline=session(model);lib=ctypes.CDLL(str(args.library.resolve()))
    rows=[];rng=random.Random(8826)
    expected,expected_length=baseline.run(None,feed)
    for name in names:
        graph=candidate(model,[name],quant=args.quant);hardware=session(graph,args.library)
        oracle=session(candidate(model,[name],True,args.quant),args.library)
        reference,ref_length=oracle.run(None,feed)
        before=stats(lib);actual,actual_length=hardware.run(None,feed);after=stats(lib)
        if after['physical_calls']<=before['physical_calls']:raise AssertionError('No physical FPGA call')
        np.testing.assert_array_equal(actual,reference)
        np.testing.assert_array_equal(actual_length,ref_length)
        np.testing.assert_array_equal(actual_length,expected_length)
        oracle_text=decode(reference[0],ref_length[0],vocab)
        baseline_times=[];hardware_times=[];environments=[]
        for _ in range(3):baseline.run(None,feed);hardware.run(None,feed)
        before=stats(lib)
        for i in range(args.runs):
            environments.append(environment());order=['baseline','hardware'];rng.shuffle(order)
            for kind in order:
                if args.reload_weights and kind=='hardware':lib.fpga_ort_forget_residency()
                start=time.perf_counter();(baseline if kind=='baseline' else hardware).run(None,feed)
                (baseline_times if kind=='baseline' else hardware_times).append(time.perf_counter()-start)
        after=stats(lib)
        row={'node':name,'physical_oracle_bit_parity':True,'transcript':oracle_text,
             'cpu_transcript':decode(expected[0],expected_length[0],vocab),
             'cpu_seconds':baseline_times,'fpga_seconds':hardware_times,
             'cpu_p50':float(np.median(baseline_times)),'fpga_p50':float(np.median(hardware_times)),
             'stats_delta':{k:after[k]-before[k] for k in after},'environments':environments}
        rows.append(row)
        print(name,'CPU',row['cpu_p50'],'FPGA',row['fpga_p50'],flush=True)
        del hardware,oracle
        write_json(args.out,{'hardware_execution':True,'model_sha256':sha(args.model),
                            'library_sha256':sha(args.library),'audio_sha256':sha(args.wav),
                            'ranking':ranking,'rows':rows,'scope':'screening; inference-only timing',
                            'weight_reload_included':args.reload_weights,'full_acceptance_claimed':False})


if __name__=='__main__':main()
