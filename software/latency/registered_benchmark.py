"""Shared, artifact-bound sessions and full audio timing for chain experiments."""
import ctypes,json,os,subprocess,sys,time
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
sys.path.insert(0,str(ROOT/'software/ort_fpga_bulk'))
sys.path.insert(0,str(ROOT/'software/ort_fpga_shortwide'))
sys.path.insert(0,str(ROOT/'software/ort_fpga_stream_registered'))
from common import Frontend,read_audio,decode,sha,write_json,environment,identity,corpus
from pair_graph import candidate
from stream_graph import compile_chains
from boundary_lut import transform
from residual_tail import transform as tails
from probe import stats
from dma_irq import snapshot,configure


def artifacts():
    directory=ROOT/'research/export/citrinet-256-ls'
    path=ROOT/'research/fused/cpu-int8-cse.onnx';parent=json.loads(path.with_suffix('.json').read_text())
    assert sha(path)==parent['model_sha256'] and identity(directory)==parent['source_identity']
    proof=json.loads((ROOT/'reports/fused/registered_transport_evidence.json').read_text())
    assert proof['complete'] and proof['setup_slack_ns']>=0 and proof['hold_slack_ns']>=0
    library=ROOT/'software/ort_fpga_stream_registered/libort_fpga.so';boundary=ROOT/'software/latency/libboundary_lut.so'
    firmware=Path('/lib/firmware/xilinx/asr-v3-stream/asr-v3-stream.bit.bin')
    driver=ROOT/'deployment/experimental-stream-registered/qn_tile.ko'
    for p in (library,boundary,driver,ROOT/'software/latency/libresidual_tail.so'):assert sha(p)==proof['sources_and_evidence_sha256'][p.relative_to(ROOT).as_posix()]
    assert sha(firmware)==proof['firmware_bin_sha256']
    clock=int(Path('/sys/bus/platform/devices/asr-v3-stream-clock/set_rate').read_text())
    assert abs(clock-100000000)<=1 # Provider reports 99,999,999 Hz for the 100 MHz request.
    assert Path('/sys/module/qn_tile/parameters/registered_stream_protocol').read_text().strip()=='1'
    assert Path('/sys/module/qn_tile/srcversion').read_text().strip()==subprocess.check_output(['modinfo','-F','srcversion',str(driver)],text=True).strip()
    cpu,records=transform(onnx.load(path))
    physical,groups=compile_chains(transform(candidate(onnx.load(path),False)[0])[0])
    oracle,oracle_groups=compile_chains(transform(candidate(onnx.load(path),True)[0])[0],True)
    assert len(groups)==23 and sum(len(g['pairs']) for g in groups)==100
    cpu,tail_records=tails(cpu);physical,_=tails(physical);oracle,_=tails(oracle)
    return {'cpu':cpu,'fpga':physical,'oracle':oracle,'groups':groups,'boundary_records':records,
            'directory':directory,'library':library,'boundary_library':boundary,'driver':driver,
            'firmware':firmware,'model':path,'firmware_proof':proof,'clock_readback_hz':clock}


def make_session(graph,config,libraries=()):
    opt=ort.SessionOptions();opt.intra_op_num_threads=config['threads'];opt.inter_op_num_threads=1
    opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
    opt.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED if config['level']=='extended' else ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opt.log_severity_level=3
    for key,value in [('session.intra_op.allow_spinning','1' if config['spin'] else '0'),
                      ('session.inter_op.allow_spinning','0'),('session.intra_op.spin_duration_us',str(config['spin'])),
                      ('session.intra_op.spin_backoff_max','8')]:opt.add_session_config_entry(key,value)
    if config['threads']>1:opt.add_session_config_entry('session.intra_op_thread_affinities',';'.join(str(i+1) for i in range(config['threads']-1)))
    libraries=list(libraries)
    if any(n.domain=='prototype.cpu.residual' for n in graph.graph.node):libraries.append(ROOT/'software/latency/libresidual_tail.so')
    for p in libraries:opt.register_custom_ops_library(str(p))
    return ort.InferenceSession(onnx.shape_inference.infer_shapes(graph).SerializeToString(),opt,providers=['CPUExecutionProvider'])


class AudioTimer:
    def __init__(self,items):
        self.items=items;self.lib=ctypes.CDLL(str(items['library']))
        self.frontend=Frontend(items['directory']);self.vocab=(items['directory']/'vocab.txt').read_text().splitlines()
    def call(self,runner,audio,kind):
        before=stats(self.lib);start=time.perf_counter()
        x,n=self.frontend(audio);x=np.ascontiguousarray(x[:,:,:int(n[0])]);middle=time.perf_counter()
        logits,length=runner.run(None,{'features':x,'feature_lengths':n});end_model=time.perf_counter()
        text=decode(logits[0],length[0],self.vocab);end=time.perf_counter()
        delta={k:v-before[k] for k,v in stats(self.lib).items()}
        assert delta['physical_calls']==(100 if kind=='fpga' else 0)
        assert delta['oracle_calls']==(100 if kind=='oracle' else 0)
        return {'seconds':end-start,'frontend_seconds':middle-start,'model_seconds':end_model-middle,
                'decode_seconds':end-end_model,'text':text,'length':int(length[0]),
                'feature_frames':int(n[0]),'counters':delta},logits


def bindings(items):
    return {'cpu_model_sha256':sha(items['model']),'library_sha256':sha(items['library']),
            'boundary_library_sha256':sha(items['boundary_library']),'driver_sha256':sha(items['driver']),
            'firmware_sha256':sha(items['firmware']),'clock_hz':100000000,'clock_readback_hz':items['clock_readback_hz'],
            'graph_compiler_sha256':sha(ROOT/'software/ort_fpga_stream_registered/stream_graph.py'),
            'boundary_transform_sha256':sha(ROOT/'software/latency/boundary_lut.py'),
            'residual_tail_library_sha256':sha(ROOT/'software/latency/libresidual_tail.so'),
            'pair_compiler_sha256':sha(ROOT/'software/ort_fpga_stream_registered/pair_graph.py'),
            'timer_source_sha256':sha(__file__),'hardware_execution':True,'capture_tested':False,
            'representative_corpus_qualified':False,'warm_transactions':23,'retained_pairs':100,'weight_updates_per_inference':200,'weight_transfers_inside_timing':True,
            'retained_boundaries':77,'maximum_feature_frames':256,'kernel_program_cache':True}
