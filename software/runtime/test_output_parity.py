import unittest
from unittest.mock import patch
import json
from pathlib import Path
import tempfile
import numpy as np
from validate_outputs import implementation_parity,positive_dma
import citrinet_adapter

class OutputParityTests(unittest.TestCase):
    def setUp(self):
        self.expected=[np.array([[[-1.,-2.],[-3.,-4.]]],np.float32),np.array([2],np.int64)]
    def compare(self,actual,text='one'):
        return implementation_parity(self.expected,actual,'one',text)['passed']
    def test_expected_native_result(self):
        actual=[self.expected[0]+np.float32(1e-5),self.expected[1].copy()]
        self.assertTrue(self.compare(actual))
    def test_wrong_arithmetic_rejected(self):
        actual=[self.expected[0].copy(),self.expected[1].copy()]
        actual[0][0,1,1]+=np.float32(.01)
        self.assertFalse(self.compare(actual))
    def test_wrong_lengths_rejected(self):
        self.assertFalse(self.compare([self.expected[0],np.array([1],np.int64)]))
    def test_broadcast_shape_rejected(self):
        self.assertFalse(self.compare([self.expected[0][:,:,:1],self.expected[1]]))
    def test_nonfinite_rejected(self):
        actual=[self.expected[0].copy(),self.expected[1]];actual[0][0,0,0]=np.nan
        self.assertFalse(self.compare(actual))
    def test_decoding_mismatch_rejected(self): self.assertFalse(self.compare(self.expected,'two'))
    def test_invalid_encoded_range_rejected(self):
        self.assertFalse(self.compare([self.expected[0],np.array([3],np.int64)]))
    def test_positive_physical_commands_required(self):
        stats={k:1 for k in ('loads','runs','ioctls','tx_bytes','rx_bytes')}
        self.assertTrue(positive_dma(stats));stats['runs']=0;self.assertFalse(positive_dma(stats))
    def test_runner_metadata_hash_failure_closes_device(self):
        class Device:
            closed=False
            def close(self): self.closed=True
        device=Device()
        with patch.object(citrinet_adapter,'NativeCachedDevice',return_value=device), \
             patch.object(citrinet_adapter,'PartitionGraph',return_value=object()), \
             patch.object(citrinet_adapter,'digest',side_effect=OSError('hash input unavailable')):
            with self.assertRaises(OSError): citrinet_adapter.Runner('fpga',4)
        self.assertTrue(device.closed)
    def test_validation_flags_default_false(self):
        metadata={'original_nemo_wrapper_validated':False,'hardware_execution':False}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder, \
             patch.object(citrinet_adapter,'ROOT',Path(folder)), \
             patch.dict(citrinet_adapter.os.environ,{},clear=True):
            citrinet_adapter.bind_validation_reports(metadata)
        self.assertFalse(metadata['original_model_output_parity_validated'])
        self.assertFalse(metadata['physical_quantized_graph_parity_validated'])
    def test_original_proof_must_bind_current_artifacts(self):
        metadata={k:'a'*64 for k in ('model_sha256','tokenizer_sha256','preprocessing_id','decoder_id',
                                    'checkpoint_sha256','frontend_constants_sha256','frontend_source_sha256','decoder_sha256')}
        metadata.update(original_nemo_wrapper_validated=False,hardware_execution=False)
        report=dict(metadata,status='pass',complete_original_nemo_wrapper_validated=True,tests=[{'waveform':'fixture'}])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path=Path(folder)/'proof.json';path.write_text(json.dumps(report))
            with patch.dict(citrinet_adapter.os.environ,{'CITRINET_ORIGINAL_PARITY_REPORT':str(path)},clear=True):
                citrinet_adapter.bind_validation_reports(metadata)
                self.assertTrue(metadata['original_model_output_parity_validated'])
                metadata['model_sha256']='b'*64
                with self.assertRaises(ValueError): citrinet_adapter.bind_validation_reports(metadata)
    def test_physical_proof_checks_source_binary_and_tolerance(self):
        keys=('model_sha256','tokenizer_sha256','preprocessing_id','decoder_id','native_library_sha256')
        metadata={k:'a'*64 for k in keys};metadata.update(hardware_execution=True,source_sha256={'source':'a'*64})
        proof=implementation_parity(self.expected,self.expected,'one','one')
        proof['positive_physical_dma_work']=True
        report={'hardware_execution':True,'metadata':metadata.copy(),
                'physical_vs_numerical_int8_implementation_parity':proof,
                'dma':{k:1 for k in ('loads','runs','ioctls','tx_bytes','rx_bytes')}}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path=Path(folder)/'proof.json';path.write_text(json.dumps(report))
            with patch.object(citrinet_adapter,'ROOT',Path(folder)), \
                 patch.dict(citrinet_adapter.os.environ,{'CITRINET_PHYSICAL_PARITY_REPORT':str(path)},clear=True):
                citrinet_adapter.bind_validation_reports(metadata)
                self.assertTrue(metadata['physical_quantized_graph_parity_validated'])
                metadata['native_library_sha256']='b'*64
                with self.assertRaises(ValueError): citrinet_adapter.bind_validation_reports(metadata)
                metadata['native_library_sha256']='a'*64;proof['relative_tolerance']=1
                path.write_text(json.dumps(report))
                with self.assertRaises(ValueError): citrinet_adapter.bind_validation_reports(metadata)

if __name__=='__main__': unittest.main()
