"""Paired original/vector operator timings; not full ASR or FPGA speedup."""
import argparse,copy,json,os,sys,time
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
from onnx import helper,TensorProto
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
from common import sha,write_json

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--runs',type=int,default=100);a=ap.parse_args()
    assert a.runs>=30
    proof=json.loads((ROOT/'reports/fused/residual_tail_maskfast_validation.json').read_text())
    assert proof['complete'] and proof['all_bit_exact'] and len(proof['full_model_cases'])==36
    original=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
    constants={v.name:v for v in original.graph.initializer}
    libs=[ROOT/'software/latency/libresidual_tail.so',ROOT/'software/latency/libresidual_tail_maskfast.so']
    assert sha(libs[1])==proof['library_sha256']
    rng=np.random.default_rng(20261013);rows=[];affinity=os.sched_getaffinity(0)
    try:
        os.sched_setaffinity(0,{3})
        for index,record in enumerate(proof['records']):
            inputs=record['inputs']
            for times in (1,13,26,63,126):
                channels=256
                values=[helper.make_tensor_value_info(name,kind,shape) for name,kind,shape in
                        zip(inputs[:4],(TensorProto.FLOAT,TensorProto.FLOAT,TensorProto.UINT8,TensorProto.BOOL),
                            ([1,channels,times],[1,channels,1],[1,channels,times],[1,1,times]))]
                output='y';info=helper.make_tensor_value_info(output,TensorProto.UINT8,[1,channels,times])
                node=helper.make_node('ResidualTail',inputs,[output],domain='prototype.cpu.residual',relu=int(record['relu']))
                model=helper.make_model(helper.make_graph([node],'tail-vector-bench',values,[info],
                                                       [copy.deepcopy(constants[i]) for i in inputs[4:]]),
                                        opset_imports=[helper.make_opsetid('',17),helper.make_opsetid('prototype.cpu.residual',1)])
                model.ir_version=10;runners=[]
                for library in libs:
                    opt=ort.SessionOptions();opt.intra_op_num_threads=1;opt.inter_op_num_threads=1
                    opt.add_session_config_entry('session.intra_op.allow_spinning','0');opt.log_severity_level=3
                    opt.register_custom_ops_library(str(library))
                    runners.append(ort.InferenceSession(model.SerializeToString(),opt,providers=['CPUExecutionProvider']))
                mask=np.zeros((1,1,times),np.bool_) # All-valid hot path; masked parity is tested separately.
                feed=dict(zip(inputs[:4],(rng.uniform(-50,50,(1,channels,times)).astype(np.float32),
                                         rng.uniform(0,1,(1,channels,1)).astype(np.float32),
                                         rng.integers(0,256,(1,channels,times),dtype=np.uint8),mask)))
                np.testing.assert_array_equal(runners[0].run(None,feed),runners[1].run(None,feed))
                for runner in runners:
                    for _ in range(5):runner.run(None,feed)
                samples=[[],[]]
                for pair in range(a.runs):
                    for order in ((0,1) if pair%2==0 else (1,0)):
                        start=time.perf_counter_ns();runners[order].run(None,feed)
                        samples[order].append((time.perf_counter_ns()-start)/1000)
                medians=[float(np.median(s)) for s in samples]
                rows.append({'region':index,'times':times,'channels':channels,'mask':'all_valid','bit_exact':True,
                             'original_p50_us':medians[0],'vector_p50_us':medians[1],
                             'reduction_percent':100*(1-medians[1]/medians[0]),'paired_samples_us':samples})
                del runners
            print('Completed region',index,flush=True)
    finally:os.sched_setaffinity(0,affinity)
    write_json(ROOT/'reports/fused/residual_tail_maskfast_operator_benchmark.json',{
        'complete':True,'hardware_execution':False,'timing_acceptance':False,'operator_only':True,
        'runs_per_case':a.runs,'all_outputs_bit_exact':True,'cases':rows,
        'original_library_sha256':sha(libs[0]),'vector_library_sha256':sha(libs[1]),
        'source_sha256':sha(__file__),'validation_sha256':sha(ROOT/'reports/fused/residual_tail_maskfast_validation.json'),
        'note':'Paired single-operator timing; apply to both CPU and hybrid and retest full-path latency before adoption'})

if __name__=='__main__':main()
