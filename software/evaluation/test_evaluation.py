import unittest
from benchmark import errors, percentile, words,resident_runners,validate_execution

class EvaluationTests(unittest.TestCase):
    def test_edit_distance(self):
        self.assertEqual(errors('one two three','one four three five'),(2,3))
        self.assertEqual(errors('one two',''),(2,2))
        self.assertEqual(errors('','one'),(1,0))
    def test_normalization(self):
        self.assertEqual(words("Hello, WORLD! It's 42."),['hello','world',"it's",'42'])
    def test_tail(self):
        self.assertAlmostEqual(percentile(list(range(20)),.95),18.05)
    def test_cleanup_if_second_runner_initialization_fails(self):
        closed=[]
        class Stub:
            def close(self): closed.append('cpu')
        def factory(mode,threads):
            if mode=='fpga': raise RuntimeError('device unavailable')
            return Stub()
        with self.assertRaises(RuntimeError):
            with resident_runners(factory,4): pass
        self.assertEqual(closed,['cpu'])
    def test_cleanup_on_metadata_failure(self):
        closed=[]
        class Stub:
            def __init__(self,mode): self.mode=mode
            def metadata(self): raise ValueError('wrong model')
            def close(self): closed.append(self.mode)
        with self.assertRaises(ValueError):
            with resident_runners(lambda mode,threads:Stub(mode),4) as (runners,initialization):
                runners['fpga'].metadata()
        self.assertEqual(closed,['fpga','cpu'])
    def test_each_hardware_call_requires_positive_work(self):
        stats={k:1 for k in ('loads','runs','ioctls','tx_bytes','rx_bytes')}
        validate_execution({'hardware_execution':True,'dma':stats},'fpga')
        stats['runs']=0
        with self.assertRaises(ValueError): validate_execution({'hardware_execution':True,'dma':stats},'fpga')
        with self.assertRaises(ValueError): validate_execution({'hardware_execution':False,'dma':stats},'fpga')

if __name__=='__main__': unittest.main()
