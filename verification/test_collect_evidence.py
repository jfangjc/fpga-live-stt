import json
from pathlib import Path
import tempfile
import unittest
import hashlib
from collect_evidence import collect,sha,thermal

class Collection(unittest.TestCase):
    def fixture(self,folder):
        root=Path(folder);model=root/'research/export/citrinet-256-ls';model.mkdir(parents=True)
        paths=['model.onnx','vocab.txt','frontend.npz']
        for name in paths:(model/name).write_text(name)
        for name in ['software/model-tools/citrinet_cpu.py','software/model-tools/validate_nemo.py','software/native/libqnc.so','firmware.bin','driver.ko']:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name)
        source={'software/model-tools/citrinet_cpu.py':sha(root/'software/model-tools/citrinet_cpu.py')}
        c=source['software/model-tools/citrinet_cpu.py'];front=sha(model/'frontend.npz')
        identity=dict(model_sha256=sha(model/'model.onnx'),tokenizer_sha256=sha(model/'vocab.txt'),
            decoder_id=c,preprocessing_id=hashlib.sha256((front+c).encode()).hexdigest())
        original=dict(**identity,status='pass',complete_original_nemo_wrapper_validated=True,tests=[{}],
            frontend_npz_sha256=front,citrinet_cpu_source_sha256=c,validate_nemo_source_sha256=sha(root/'software/model-tools/validate_nemo.py'))
        (root/'original.json').write_text(json.dumps(original))
        meta=dict(**identity,source_sha256=source,native_library_sha256=sha(root/'software/native/libqnc.so'))
        dma={k:1 for k in ['loads','runs','ioctls','tx_bytes','rx_bytes']}
        proof={k:True for k in ['passed','positive_physical_dma_work','shapes_equal','finite','encoded_lengths_equal','encoded_lengths_valid','logits_within_tolerance','transcripts_match']}
        proof.update(absolute_tolerance=1e-4,relative_tolerance=1e-5)
        physical=dict(hardware_execution=True,mode='fpga',metadata=meta,dma=dma,physical_vs_numerical_int8_implementation_parity=proof)
        (root/'physical.json').write_text(json.dumps(physical))
        cap=dict(passed=True,hardware_execution=True,sample_rate=16000,samples=10000,errors=[],newly_dropped_samples=0,software_dropped_samples=0)
        (root/'capture.json').write_text(json.dumps(cap))
        records=[dict(id='test',text='hello world',audio_sha256='a'*64)]
        (root/'manifest.jsonl').write_text(json.dumps(records[0])+'\n')
        original_binding=dict(original_model_output_parity_validated=True,original_model_output_parity_report_sha256=sha(root/'original.json'))
        fm=dict(**meta,**original_binding,hardware_execution=True,physical_quantized_graph_parity_validated=True,
            physical_quantized_graph_parity_report_sha256=sha(root/'physical.json'),calibration_audio_sha256=[])
        cm=dict(**meta,**original_binding,hardware_execution=False)
        environment=dict(machine='aarch64',thermal_millicelsius={'temp':'42000'})
        bench=dict(measured_on_physical_board=True,metadata=dict(cpu=cm,fpga=fm),manifest_sha256=sha(root/'manifest.jsonl'),corpus=records,
            samples=[dict(mode='fpga',environment_before=environment,environment_after=environment,runner_details=dict(hardware_execution=True,dma=dma))])
        (root/'benchmark.json').write_text(json.dumps(bench))
        return root

    def call(self,root):
        return collect(*(root/name for name in ['benchmark.json','original.json','physical.json','capture.json','manifest.jsonl']),
            root,root/'firmware.bin',root/'driver.ko',True,'Reviewed optimized full-processing resident runner and concurrent capture')

    def test_valid_binding(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=self.fixture(folder);result=self.call(root)
            self.assertEqual(result['thermal_before_c'],42)
            self.assertEqual(result['capture_software_dropped_samples'],0)

    def test_stale_source(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=self.fixture(folder);(root/'software/model-tools/citrinet_cpu.py').write_text('changed')
            with self.assertRaises(ValueError):self.call(root)

    def test_missing_thermal(self):
        with self.assertRaises(ValueError):thermal({'thermal_millicelsius':{'x':None}})

    def test_failed_capture(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=self.fixture(folder);(root/'capture.json').write_text(json.dumps(dict(passed=False)))
            with self.assertRaises(ValueError):self.call(root)

if __name__=='__main__':unittest.main()
