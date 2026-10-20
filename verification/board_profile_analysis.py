"""Map user-reported ordered board profiles to artifact-verified graph steps."""
import hashlib
import json
from pathlib import Path
import re
import statistics
import zipfile
from collections import Counter,defaultdict
import onnx
from onnx import helper,numpy_helper

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'reports/board_received/2026-10-09_reference'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    board=json.loads((EVIDENCE/'reference-fpga-board.json').read_text())
    cpu=json.loads((EVIDENCE/'reference-cpu-board.json').read_text())
    metadata=board['metadata'];modelpath=ROOT/'research/export/citrinet-256-ls/model.onnx'
    assert sha(modelpath)==metadata['model_sha256']==cpu['metadata']['model_sha256']
    assert sha(modelpath.with_name('vocab.txt'))==metadata['tokenizer_sha256']==cpu['metadata']['tokenizer_sha256']
    sources={}
    archive=ROOT/'prototype-v2-package.zip'
    with zipfile.ZipFile(archive) as z:
        for relative,expected in metadata['source_sha256'].items():
            p=ROOT/relative;matches=[]
            for name in z.namelist():
                if name.replace('\\','/').endswith(relative):
                    if hashlib.sha256(z.read(name)).hexdigest()==expected:matches.append(name)
            sources[relative]=dict(recorded=expected,current=sha(p),current_matches=sha(p)==expected,archive_matching_members=matches)
    model=onnx.load(modelpath);nodes=list(model.graph.node)
    arrays={v.name:numpy_helper.to_array(v) for v in model.graph.initializer}
    accelerated=set(metadata['accelerated_nodes'])
    assert len(accelerated)==len(metadata['accelerated_nodes'])
    mapping=[];i=0
    while i<len(nodes):
        if nodes[i].name in accelerated:
            mapping.append(('fpga',[nodes[i]]));i+=1
        else:
            end=i+1
            while end<len(nodes) and nodes[end].name not in accelerated:end+=1
            mapping.append(('cpu',nodes[i:end]));i=end
    assert sum(kind=='fpga' for kind,_ in mapping)==126
    for run in board['runs']:
        assert len(mapping)==len(run['partition_profile'])
        assert all(kind==row['kind'] for (kind,_),row in zip(mapping,run['partition_profile']))
    # The archived partition implementation and current graph/node identities
    # bind these labels even if follow-up local source has changed.
    partition_source=sources['software/runtime/partition.py']
    assert partition_source['current_matches'] or partition_source['archive_matching_members'],'Recorded partition source not available for audit'
    steps=[]
    for index,(kind,subset) in enumerate(mapping):
        times=[r['partition_profile'][index]['seconds'] for r in board['runs']]
        convs=[]
        for node in subset:
            if node.op_type!='Conv':continue
            a={v.name:helper.get_attribute_value(v) for v in node.attribute};w=arrays.get(node.input[1])
            convs.append(dict(name=node.name,weights_shape=list(w.shape) if w is not None else None,
                group=a.get('group',1),strides=a.get('strides',[1]),
                operator='depthwise' if w is not None and a.get('group',1)==w.shape[0] and w.shape[1]==1 else 'pointwise' if w is not None and w.shape[-1]==1 else 'other_conv'))
        names=[n.name for n in subset]
        blocks=sorted(set(m.group(1) for name in names if (m:=re.search(r'encoder\.(\d+)',name))))
        steps.append(dict(index=index,kind=kind,median_seconds=statistics.median(times),mean_seconds=statistics.mean(times),
            min_seconds=min(times),max_seconds=max(times),node_count=len(subset),operators=dict(Counter(n.op_type for n in subset)),
            first_node=names[0],last_node=names[-1],encoder_blocks=blocks,convolutions=convs))
    cpu_total=statistics.median([sum(r['seconds'] for r in run['partition_profile'] if r['kind']=='cpu') for run in board['runs']])
    fpga_total=statistics.median([sum(r['seconds'] for r in run['partition_profile'] if r['kind']=='fpga') for run in board['runs']])
    hybrid=statistics.median(r['total_seconds'] for r in board['runs']);baseline=statistics.median(r['total_seconds'] for r in cpu['runs'])
    ioctl=statistics.median(r['dma']['ioctl_seconds'] for r in board['runs'])
    outside=statistics.median(sum(p['seconds'] for p in r['partition_profile'] if p['kind']=='fpga')-r['dma']['ioctl_seconds'] for r in board['runs'])
    category=defaultdict(float)
    fpga_block=defaultdict(float);cpu_stride_pointwise=[]
    for s in steps:
        if s['kind']=='fpga':
            fpga_block[s['encoder_blocks'][0] if s['encoder_blocks'] else 'decoder']+=s['mean_seconds']
            continue
        cpu_stride_pointwise.extend(dict(step_index=s['index'],region_mean_seconds=s['mean_seconds'],**c) for c in s['convolutions'] if c['operator']=='pointwise')
        label='depthwise+region_operations' if any(c['operator']=='depthwise' for c in s['convolutions']) else 'other_conv+region_operations' if s['convolutions'] else 'SE_mask_residual_activation_or_output_only'
        category[label]+=s['mean_seconds']
    result=dict(evidence_origin='User-pasted KV260 console output, not re-executed by verifier',
        model_and_tokenizer_match=True,source_provenance=sources,archive_sha256=sha(archive),
        mapping_method='Contiguous ONNX node regions split on exactly the recorded accelerated node names; 253 ordered kind entries matched every run; archived partition source hash verified',
        cpu_regions=sum(s['kind']=='cpu' for s in steps),fpga_nodes=sum(s['kind']=='fpga' for s in steps),
        cpu_region_categories_mean_seconds=dict(category),
        pointwise_blocks_mean_seconds=dict(fpga_block),cpu_unaccelerated_pointwise=cpu_stride_pointwise,
        budget=dict(cpu_baseline_p50_seconds=baseline,hybrid_p50_seconds=hybrid,target_seconds=.8*baseline,
            reduction_needed_seconds=hybrid-.8*baseline,cpu_region_p50_seconds=cpu_total,pointwise_p50_seconds=fpga_total,
            ioctl_p50_seconds=ioctl,pointwise_outside_ioctl_p50_seconds=outside,
            all_pointwise_removed_floor_seconds=hybrid-fpga_total,
            all_ioctl_removed_floor_seconds=hybrid-ioctl,
            all_native_host_pointwise_removed_floor_seconds=hybrid-outside),
        cpu_hotspots=sorted((s for s in steps if s['kind']=='cpu'),key=lambda s:s['mean_seconds'],reverse=True)[:15],
        fpga_hotspots=sorted((s for s in steps if s['kind']=='fpga'),key=lambda s:s['mean_seconds'],reverse=True)[:15],
        all_steps=steps,limitations=['Only three warm runs and one clip; percentile acceptance and corpus WER absent','CPU region time includes ORT scheduling, masks, activations, residuals, depthwise and SE; individual node attribution requires ORT profiling','Pointwise time includes native host quantization/packing/load/ioctl/unpack/bias, not isolated FPGA compute','Current source may differ; mapping anchored to archived measured partition source','Clock/thermal/firmware identity absent from user-pasted evidence'])
    (ROOT/'verification/board_profile_analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    concise={k:result[k] for k in ['budget','cpu_region_categories_mean_seconds','pointwise_blocks_mean_seconds','cpu_unaccelerated_pointwise']}
    concise['cpu_top5']=[dict(index=s['index'],first=s['first_node'],last=s['last_node'],mean_ms=1000*s['mean_seconds']) for s in result['cpu_hotspots'][:5]]
    concise['fpga_top5']=[dict(node=s['first_node'],mean_ms=1000*s['mean_seconds']) for s in result['fpga_hotspots'][:5]]
    print(json.dumps(concise,indent=2))

if __name__=='__main__':main()
