"""Count actual QNC2 packets for a full 10-second graph in host emulation.

This validates protocol traffic and numerical parity, not FPGA throughput.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import numpy as np

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'software'),str(root/'software/asr-baseline')]
from cached_smoke import EmulatedCached
from qn_cached import MAX_BATCH_PACKETS,MAX_BATCH_RX_BYTES,output_bytes as response_bytes
from quartznet_hybrid import Graph
from quartznet_cpu import read_pcm24,frontend

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--wav',type=Path)
parser.add_argument('--report',type=Path,default=root/'reports/cached_architecture_estimate.json')
args=parser.parse_args()
if args.wav:
    audio=read_pcm24(args.wav)
    audio-=audio.mean()
    features,valid=frontend(audio)
    features=features[:,:,:valid].copy()
    feature_source={'wav':str(args.wav),'wav_sha256':hashlib.sha256(args.wav.read_bytes()).hexdigest(),
                    'remove_dc':True,'audio_seconds':len(audio)/16000}
else:
    features=np.random.default_rng(20261008).normal(size=(1,64,1000)).astype(np.float32)
    feature_source={'kind':'deterministic synthetic 1000 feature frames','seed':20261008}
if features.shape!=(1,64,1000):
    raise ValueError(f'Expected ten-second frontend shape [1,64,1000], got {features.shape}')

hashes={}
def remember(node,result):
    hashes[node.name]=hashlib.sha256(result.tobytes()).hexdigest()
def compare(node,result):
    if hashlib.sha256(result.tobytes()).hexdigest()!=hashes[node.name]:
        raise AssertionError(f'Node mismatch: {node.name}')
model=root/'software/asr-baseline/model/model.onnx'
reference=Graph(model,mode='emulate')
expected=reference.run(features,observer=remember)
transport=EmulatedCached()
graph=Graph(model,mode='dma',transact=transport,pointwise_backend='cached')
actual=graph.run(features,observer=compare)
np.testing.assert_array_equal(actual,expected)
layers=[]
weight_payload=input_payload=output_payload=0
for node,stat in zip(graph.nodes,graph.stats):
    if not stat['int8_pointwise']:
        continue
    m,k=graph.quantized[node.name][0].shape
    t=stat['shape'][2]
    groups=(m+15)//16
    blocks=(t+15)//16
    weight_bytes=groups*k*16
    input_bytes=blocks*k*16
    output_bytes=blocks*groups*1024
    weight_payload+=weight_bytes
    input_payload+=input_bytes
    output_payload+=output_bytes
    assert stat['cached_load_commands']==1
    assert stat['cached_run_commands']==blocks
    batch_limit=min(transport.max_batch_packets,MAX_BATCH_PACKETS,MAX_BATCH_RX_BYTES//response_bytes(m))
    run_batches=(blocks+batch_limit-1)//batch_limit
    assert stat['dma_ioctl_calls']==1+run_batches
    assert stat['dma_input_bytes']==weight_bytes+input_bytes+16*(1+blocks)
    layers.append({'name':node.name,'k':k,'m':m,'time_frames':t,'output_groups':groups,
                   'load_commands':1,'run_commands':blocks,'run_batch_limit':batch_limit,
                   'run_batch_calls':run_batches,'ioctl_calls':1+run_batches,
                   'weight_payload_bytes':weight_bytes,'input_payload_bytes':input_bytes,
                   'response_payload_bytes':output_bytes})
commands=transport.load_commands+transport.run_commands
assert transport.input_bytes_sent==weight_payload+input_payload+commands*16
assert transport.output_bytes_received==output_payload+commands*16
old_input=1094902784
old_ioctls=605
result={'result':'PASS','hardware_execution':False,'measurement_kind':'host protocol emulation',
        'source':feature_source,'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
        'features_shape':list(features.shape),'all_266_node_outputs_bit_exact':True,
        'pointwise_layers':len(layers),'load_commands':transport.load_commands,
        'run_commands':transport.run_commands,'ioctl_calls':transport.ioctl_calls,
        'run_batch_ioctl_calls':transport.ioctl_calls-transport.load_commands,
        'cached_batch_size_limit':transport.max_batch_packets,
        'batch_rx_buffer_bytes':MAX_BATCH_RX_BYTES,
        'computed_tile_groups':transport.tile_packets,
        'weight_payload_bytes':weight_payload,'reused_input_payload_bytes':input_payload,
        'command_header_bytes':commands*16,'dma_input_bytes':transport.input_bytes_sent,
        'int32_response_payload_bytes':output_payload,'response_header_bytes':commands*16,
        'dma_output_bytes':transport.output_bytes_received,
        'previous_board_batch128_dma_input_bytes':old_input,'previous_board_batch128_ioctl_calls':old_ioctls,
        'input_reduction_percent':100*(1-transport.input_bytes_sent/old_input),
        'input_reduction_factor':old_input/transport.input_bytes_sent,
        'ioctl_count_ratio_to_previous_batch128':transport.ioctl_calls/old_ioctls,
        'limitations':['Host emulation is not a board latency, power, WER or driver measurement.',
                       'LOAD uses one ioctl; RUN packets use bounded homogeneous batches constrained by the RX buffer.',
                       'Cached LOAD acknowledgements add 94 ioctls relative to prior tile batch128 execution on this clip.',
                       'FP32 bias/dequantization and depthwise processing remain on CPU.',
                       'Weight LOAD occurs once per pointwise layer per graph execution; complete model is not resident on chip.'],
        'layers':layers}
args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='layers'},indent=2))
