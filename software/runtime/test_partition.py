import tempfile
from pathlib import Path
import unittest
import numpy as np
import onnx
from onnx import helper,numpy_helper,TensorProto
import onnxruntime as ort
from partition import PartitionGraph,options

class PartitionTests(unittest.TestCase):
    def test_se_fallback_and_pointwise(self):
        rng=np.random.default_rng(13)
        w=rng.normal(size=(17,3,1)).astype(np.float32)
        nodes=[helper.make_node('Conv',['x','w'],['c'],name='pointwise'),
               helper.make_node('Relu',['c'],['r']),
               helper.make_node('ReduceMean',['r'],['s'],axes=[2],keepdims=1),
               helper.make_node('Sigmoid',['s'],['a']),helper.make_node('Mul',['r','a'],['y'])]
        graph=helper.make_graph(nodes,'fixture',[helper.make_tensor_value_info('x',TensorProto.FLOAT,[1,3,'T'])],
               [helper.make_tensor_value_info('y',TensorProto.FLOAT,[1,17,'T'])],[numpy_helper.from_array(w,'w')])
        model=helper.make_model(graph,opset_imports=[helper.make_opsetid('',17)]);model.ir_version=8
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path=Path(folder)/'fixture.onnx';onnx.save(model,path)
            part=PartitionGraph(path,emulate=True)
            self.assertEqual(part.accelerated_nodes,['pointwise'])
            x=rng.normal(size=(1,3,35)).astype(np.float32)
            actual=part.run({'x':x})[0]
            # Quantized reference graph with precisely the same activations and weights.
            scale=np.max(np.abs(w[:,:,0]),axis=1)/np.float32(127)
            act=np.max(np.abs(x))/np.float32(127)
            qw=np.clip(np.rint(w[:,:,0]/scale[:,None]),-127,127).astype(np.int8)
            qx=np.clip(np.rint(x[0]/act),-127,127).astype(np.int8)
            c=(qw.astype(np.int32)@qx.astype(np.int32)).astype(np.float32)*(scale*act)[:,None]
            r=np.maximum(c,0);a=1/(1+np.exp(-r.mean(axis=1,keepdims=True)))
            np.testing.assert_allclose(actual,(r*a)[None],rtol=2e-6,atol=2e-6)
            full=ort.InferenceSession(str(path),options(4),providers=['CPUExecutionProvider']).run(None,{'x':x})[0]
            self.assertLess(np.max(np.abs(actual-full)),.12)

if __name__=='__main__': unittest.main()
