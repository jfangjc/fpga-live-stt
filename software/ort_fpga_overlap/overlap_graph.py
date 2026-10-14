"""Fuse one independent CPU residual convolution with each block's first chain."""
import copy,heapq
import numpy as np
import onnx
from onnx import helper,numpy_helper

def fuse_residuals(model):
    graph=copy.deepcopy(model);nodes=list(graph.graph.node)
    arrays={v.name:numpy_helper.to_array(v) for v in graph.graph.initializer}
    producers={out:n for n in nodes for out in n.output};removed=set();replaced={};records=[];seen=set()
    def depends(value,outputs,visited=None):
        if value in outputs:return True
        visited=set() if visited is None else visited
        if value in visited or value not in producers:return False
        visited.add(value);return any(depends(i,outputs,visited) for i in producers[value].input)
    for chain in nodes:
        if chain.domain!='prototype.fpga.chain' or chain.op_type not in ('FpgaChain','OracleChain'):continue
        block='/'.join(chain.name.split('/')[:3])
        if block in seen:continue
        residuals=[n for n in nodes if n.name.startswith(block+'/res.') and n.op_type=='QLinearConv']
        if len(residuals)!=1:continue
        residual=residuals[0];attrs={a.name:helper.get_attribute_value(a) for a in residual.attribute}
        assert attrs.get('group',1)==1 and attrs.get('kernel_shape')==[1] and attrs.get('pads',[0,0])==[0,0]
        assert attrs.get('dilations',[1])==[1] and attrs.get('strides',[1]) in ([1],[2])
        assert not depends(residual.input[0],set(chain.output)), 'Residual must be independent of this chain'
        assert all(name in arrays for name in residual.input[1:])
        if len(residual.input)==8:
            name=residual.name+'_overlap_zero_bias';bias=np.zeros(arrays[residual.input[3]].shape[0],np.int32)
            graph.graph.initializer.append(numpy_helper.from_array(bias,name));residual.input.append(name)
        assert len(residual.input)==9
        fused=helper.make_node('OracleResidualChain' if chain.op_type=='OracleChain' else 'FpgaResidualChain',
                              list(residual.input)+list(chain.input),list(residual.output)+list(chain.output),
                              name=chain.name+'_residual_overlap',domain='prototype.fpga.overlap',res_stride=attrs.get('strides',[1])[0])
        replaced[chain.name]=fused;removed.add(residual.name);seen.add(block)
        records.append({'name':fused.name,'residual':residual.name,'chain':chain.name,'stride':attrs.get('strides',[1])[0],
                        'same_input':residual.input[0]==chain.input[0]})
    modified=[]
    for node in nodes:
        if node.name in removed:continue
        node=replaced.get(node.name,node)
        if node.domain=='prototype.fpga.chain':node.domain='prototype.fpga.overlap'
        modified.append(node)
    # Moving a residual branch earlier can require its input quantizer earlier.
    producer={out:i for i,node in enumerate(modified) for out in node.output};dependents={};degrees=[]
    for i,node in enumerate(modified):
        parents={producer[value] for value in node.input if value in producer};degrees.append(len(parents))
        for parent in parents:dependents.setdefault(parent,[]).append(i)
    ready=[i for i,degree in enumerate(degrees) if degree==0];heapq.heapify(ready);ordered=[]
    while ready:
        i=heapq.heappop(ready);ordered.append(modified[i])
        for child in dependents.get(i,[]):
            degrees[child]-=1
            if not degrees[child]:heapq.heappush(ready,child)
    assert len(ordered)==len(modified),'Overlap graph contains a cycle'
    del graph.graph.node[:];graph.graph.node.extend(ordered)
    graph.opset_import.append(helper.make_opsetid('prototype.fpga.overlap',1))
    onnx.checker.check_model(graph);assert len(records)==8,f'Expected 8 independent residual branches: {len(records)}'
    return graph,records
