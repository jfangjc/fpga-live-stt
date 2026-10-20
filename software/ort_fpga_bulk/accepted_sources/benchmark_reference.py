"""Timing regression for the original clip; its reference is model-generated."""
import benchmark
original_write=benchmark.write_json
def annotated_write(path,result):
    result['reference_is_model_prediction_not_human_ground_truth']=True
    result['wer_accuracy_claimed']=False
    original_write(path,result)
benchmark.write_json=annotated_write
if __name__=='__main__':benchmark.main()
