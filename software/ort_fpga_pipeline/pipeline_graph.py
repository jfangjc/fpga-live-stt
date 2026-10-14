"""Compile small constant CPU residual graphs for native overlapped execution."""
import sys
from pathlib import Path
import numpy as np
import onnx
from onnx import helper,numpy_helper
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'software/ort_fpga_overlap'))
from overlap_graph import fuse_residuals as base_fuse

def fuse_residuals(model):
    graph,records=base_fuse(model);arrays={v.name:numpy_helper.to_array(v) for v in graph.graph.initializer}
    for node in graph.graph.node:
        if node.domain!='prototype.fpga.overlap':continue
        node.domain='prototype.fpga.pipeline'
        if node.op_type not in ('FpgaResidualChain','OracleResidualChain'):continue
        attrs={a.name:helper.get_attribute_value(a) for a in node.attribute};stride=attrs['res_stride']
        inputs=['x']+[f'p{i}' for i in range(1,9)]
        constants=[numpy_helper.from_array(arrays[node.input[i]],inputs[i]) for i in range(1,9)]
        weight=arrays[node.input[3]]
        convolution=helper.make_node('QLinearConv',inputs,['y'],name='prepacked_residual',group=1,
                                     dilations=[1],kernel_shape=[1],pads=[0,0],strides=[stride])
        cpu_graph=helper.make_graph([convolution],'residual-cpu',
                      [helper.make_tensor_value_info('x',onnx.TensorProto.UINT8,[1,weight.shape[1],'T'])],
                      [helper.make_tensor_value_info('y',onnx.TensorProto.UINT8,[1,weight.shape[0],'Tout'])],constants)
        cpu_model=helper.make_model(cpu_graph,opset_imports=[helper.make_opsetid('',17)]);cpu_model.ir_version=10
        onnx.checker.check_model(cpu_model);name=node.name+'_cpu_graph'
        graph.graph.initializer.append(numpy_helper.from_array(np.frombuffer(cpu_model.SerializeToString(),np.uint8).copy(),name))
        node.input.append(name)
    graph.opset_import.append(helper.make_opsetid('prototype.fpga.pipeline',1));onnx.checker.check_model(graph)
    return graph,records
