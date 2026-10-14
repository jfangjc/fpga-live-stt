"""Timing regression for the original clip; its reference is model-generated."""
from pathlib import Path
import importlib.util
import probe  # Initialize the shared evaluation module before the private loader.
spec=importlib.util.spec_from_file_location('bulk_reference_runner',Path(__file__).with_name('benchmark.py'))
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
original_write=runner.write_json
def annotated_write(path,result):
    result['reference_is_model_prediction_not_human_ground_truth']=True
    result['wer_accuracy_claimed']=False
    original_write(path,result)
runner.write_json=annotated_write
if __name__=='__main__':runner.main()
