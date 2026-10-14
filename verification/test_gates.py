import copy
import unittest
from evaluate_gates import edits, evaluate, percentile, from_benchmark


def sample():
    return {'metadata': dict(board='KV260', model_sha256='a'*64,
        audio_manifest_sha256='b'*64, preprocessing_sha256='c'*64,
        decoder_sha256='d'*64, tokenizer_sha256='e'*64,
        source_provenance_sha256={'runtime.py':'f'*64},
        original_model_parity_report_sha256='1'*64,
        physical_quantized_graph_parity_report_sha256='2'*64,
        reference_transcripts_sha256='3'*64,reference_transcripts_reviewed=True,
        original_model_output_parity_validated=True,
        physical_quantized_graph_parity_validated=True,
        capture_software_dropped_samples=0,
        cpu_threads=4, cpu_precision='FP32',
        fpga_precision='INT8/INT32', clock_hz=100000000,
        thermal_before_c=40, thermal_after_c=45, initialization_seconds=1,
        calibration_ids=['cal'], evaluation_ids=['test'], full_processing_timing=True,
        warm_state_resident=True, capture_newly_dropped_samples=0,
        cpu_optimized=True, physical_fpga_execution=True,
        evaluation_categories=['quiet','accented','numbers','names','noise']),
        'rows': [dict(id='test',reference='the quick brown fox',
            cpu_text='the quick brown fox',fpga_text='the quick brown fox',
            cpu_seconds=[2.0]*10,fpga_seconds=[1.5]*10)]}


class Gates(unittest.TestCase):
    def test_levenshtein(self):
        self.assertEqual(edits('a b c', 'a x c d'), (2, 3))
        self.assertEqual(edits('', 'a'), (1, 0))
        self.assertEqual(edits('Hello, THREE!', 'hello three'), (0, 2))

    def test_percentiles(self):
        self.assertAlmostEqual(percentile([1,2,3,4], .5), 2.5)
        self.assertAlmostEqual(percentile([1,2,3,4], .95), 3.85)

    def test_valid_pass(self):
        self.assertTrue(evaluate(sample())['passed'])

    def test_speed_tail_failure(self):
        x = sample(); x['rows'][0]['fpga_seconds'][-2:] = [3,3]
        self.assertFalse(evaluate(x)['timing_gate'])

    def test_wer_failure(self):
        x = sample(); x['rows'][0]['fpga_text'] = 'the quick fox'
        self.assertFalse(evaluate(x)['accuracy_gate'])

    def test_missing_measurements(self):
        x = sample(); del x['metadata']['clock_hz']
        with self.assertRaises(ValueError): evaluate(x)

    def test_nonphysical(self):
        x = sample(); x['metadata']['physical_fpga_execution'] = False
        with self.assertRaises(ValueError): evaluate(x)

    def test_leakage(self):
        x = sample(); x['metadata']['calibration_ids'] = ['test']
        with self.assertRaises(ValueError): evaluate(x)

    def test_drops_fail(self):
        x = sample(); x['metadata']['capture_newly_dropped_samples'] = 1
        self.assertFalse(evaluate(x)['capture_gate'])

    def test_invalid_times(self):
        for v in [0, -1, float('nan'), float('inf')]:
            x = sample(); x['rows'][0]['cpu_seconds'][0] = v
            with self.assertRaises(ValueError): evaluate(x)

    def test_report_converter(self):
        x = sample()
        m = dict(model_sha256='a'*64,tokenizer_sha256='e'*64,preprocessing_id='front',decoder_id='decode',threads=4,precision='FP32')
        report = dict(measured_on_physical_board=True, metadata=dict(cpu=m,fpga={**m,'hardware_execution':True}),
            manifest_sha256='b'*64,pl_clock_hz=100000000,initialization_seconds=1,
            corpus=[dict(id='test',text='the quick brown fox',categories=['quiet','accent','numbers','names','noise'])],
            samples=[dict(id='test',mode=mode,repeat=i,transcript='the quick brown fox',total_seconds=2 if mode=='cpu' else 1.5) for mode in ['cpu','fpga'] for i in range(10)])
        self.assertTrue(evaluate(from_benchmark(report,x['metadata']))['passed'])
        report['metadata']['fpga']['original_nemo_wrapper_validated']=False
        with self.assertRaises(ValueError):evaluate(from_benchmark(report,x['metadata']))
        del report['metadata']['fpga']['original_nemo_wrapper_validated']
        report['metadata']['fpga']['physical_quantized_graph_parity_validated']=False
        with self.assertRaises(ValueError):evaluate(from_benchmark(report,x['metadata']))
        del report['metadata']['fpga']['physical_quantized_graph_parity_validated']
        report['samples'][0]['transcript']='unstable'
        with self.assertRaises(ValueError): from_benchmark(report,x['metadata'])

    def test_required_original_parity(self):
        for field in ['original_model_output_parity_validated','physical_quantized_graph_parity_validated','reference_transcripts_reviewed']:
            x=sample();x['metadata'][field]=False
            with self.assertRaises(ValueError):evaluate(x)

    def test_software_capture_drops(self):
        x=sample();x['metadata']['capture_software_dropped_samples']=16000
        self.assertFalse(evaluate(x)['capture_gate'])

    def test_provenance(self):
        for field in ['model_sha256','reference_transcripts_sha256','original_model_parity_report_sha256']:
            x=sample();x['metadata'][field]='unverified'
            with self.assertRaises(ValueError):evaluate(x)
        x=sample();x['metadata']['source_provenance_sha256']={}
        with self.assertRaises(ValueError):evaluate(x)

    def test_physical_settings(self):
        for field,value in [('clock_hz',0),('clock_hz',float('inf')),('thermal_after_c',float('nan')),('capture_software_dropped_samples',-1)]:
            x=sample();x['metadata'][field]=value
            with self.assertRaises(ValueError):evaluate(x)

    def test_unicode_normalization(self):
        self.assertEqual(edits('ＭＯＤＥＬ café ４２', 'model café 42'),(0,3))


if __name__ == '__main__': unittest.main()
