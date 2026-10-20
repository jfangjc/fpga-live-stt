#!/usr/bin/env python3
"""Checkpoint tensor census and concrete-shape work/traffic estimates."""
import collections
import hashlib
import json
from pathlib import Path
import numpy as np
import onnx
import torch
import yaml
from export_citrinet import ROOT, Model


def main():
    torch.set_num_threads(4)
    base=ROOT/'research/checkpoints/citrinet-256-ls'
    out=ROOT/'research/export/citrinet-256-ls'
    config=yaml.safe_load((base/'model_config.yaml').read_text())
    state=torch.load(base/'model_weights.ckpt',weights_only=True,map_location='cpu')
    model=Model(config,state)
    layers=[]
    for name,m in model.named_modules():
        if isinstance(m,torch.nn.Conv1d):
            def record(module,inputs,output,name=name):
                x=inputs[0]; y=output; k=module.kernel_size[0]
                pointwise=k==1 and module.groups==1
                macs=int(y.numel()*module.in_channels//module.groups*k)
                layers.append({'name':name,'input_shape':list(x.shape),'output_shape':list(y.shape),
                    'kernel':k,'stride':module.stride[0],'groups':module.groups,
                    'weights':int(module.weight.numel()),'macs':macs,'pointwise':pointwise,
                    'estimated_int8_weight_bytes':int(module.weight.numel()),
                    'estimated_int8_input_bytes':int(x.numel()),
                    'estimated_int32_result_bytes':int(y.numel()*4),
                    'estimated_fused_int8_result_bytes':int(y.numel()),
                    'old_core_padded_int32_result_bytes':int(((module.out_channels+15)//16)*16*((y.shape[-1]+15)//16)*16*4) if pointwise else None})
            m.register_forward_hook(record)
    with torch.no_grad():
        model(torch.zeros(1,80,1008),torch.tensor([1001]))
    graph=onnx.load(out/'model.onnx')
    onnx.checker.check_model(graph)
    trainable=sum(x.numel() for x in model.parameters())
    ops=dict(collections.Counter(n.op_type for n in graph.graph.node))
    pw=[x for x in layers if x['pointwise']]
    eligible=[x for x in pw if x['stride']==1]
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in base.iterdir() if p.is_file()}
    report={'checkpoint': 'nvidia/stt_en_citrinet_256_ls',
        'hf_revision':'c7cdacff0262bbb2a17771d20ec9f9f3b5cff6ed','sha256':hashes,
        'trainable_encoder_decoder_parameters':trainable,'state_elements_including_buffers':sum(x.numel() for x in state.values()),
        'tokenizer_actual':'WordPiece (wpe) with archived vocab.txt','vocabulary_size':256,'blank_index':256,
        'features':80,'window_samples':400,'fft_size':512,'hop_samples':160,
        'temporal_length_rule':'Three same-padding stride-two convolutions: ceil(feature_lengths / 8)',
        'se_blocks':23,'se_context':'Global valid utterance; not causal streaming',
        'onnx_operators':ops,'convolution_nodes':len(layers),'pointwise_nodes':len(pw),
        'shape_scenario':{'audio_samples':160000,'feature_length':1001,'padded_feature_frames':1008,'encoded_length':126},
        'estimates_not_measurements':True,
        'convolution_macs':sum(x['macs'] for x in layers),'pointwise_macs':sum(x['macs'] for x in pw),
        'pointwise_int8_weights_bytes':sum(x['weights'] for x in pw),
        'pointwise_int8_input_bytes':sum(x['estimated_int8_input_bytes'] for x in pw),
        'pointwise_int32_result_bytes':sum(x['estimated_int32_result_bytes'] for x in pw),
        'pointwise_fused_int8_result_bytes':sum(x['estimated_fused_int8_result_bytes'] for x in pw),
        'old_core_padded_int32_result_bytes':sum(x['old_core_padded_int32_result_bytes'] for x in pw),
        'adapter_eligible_nodes':len(eligible),
        'adapter_eligible_macs':sum(x['macs'] for x in eligible),
        'adapter_eligible_weight_bytes':sum(x['weights'] for x in eligible),
        'adapter_eligible_input_bytes':sum(x['estimated_int8_input_bytes'] for x in eligible),
        'adapter_eligible_padded_int32_result_bytes':sum(x['old_core_padded_int32_result_bytes'] for x in eligible),
        'adapter_omitted_pointwise_layers':[x['name'] for x in pw if x['stride']!=1],
        'ideal_pointwise_compute_seconds_at_256_mac_lanes_100mhz':sum(x['macs'] for x in pw)/25.6e9,
        'ideal_compute_limitations':'Excludes depthwise/SE/masks, memory stalls, tail lanes, weights, DMA, packing, requantization, preprocessing, decode; not a speed forecast',
        'layers':layers}
    (ROOT/'research/citrinet_inspection.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['layers','sha256']},indent=2))


if __name__=='__main__': main()
