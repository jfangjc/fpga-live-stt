#!/usr/bin/env python3
"""Full original NeMo waveform/frontend/encoder/decoder/tokenizer gate.

Uses the complete installed model class without source stubs or replacements.
Only relocates the archived tokenizer directory and disables dataset setup.
Writes success only after all supplied waveforms pass.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import numpy as np
import torch
import nemo.collections.asr as nemo_asr
from omegaconf import open_dict
from citrinet_cpu import Runtime, read_audio, decode


def main():
    p=argparse.ArgumentParser(); p.add_argument('--checkpoint-dir',type=Path,required=True)
    p.add_argument('--model-dir',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    p.add_argument('wav',type=Path,nargs='+'); args=p.parse_args()
    torch.set_num_threads(4)
    archive=args.checkpoint_dir/'stt_en_citrinet_256_ls.nemo'
    cls=nemo_asr.models.EncDecCTCModelBPE
    cfg=cls.restore_from(str(archive),return_config=True)
    with open_dict(cfg):
        cfg.tokenizer.dir=str(args.checkpoint_dir.resolve())
        cfg.train_ds=None; cfg.validation_ds=None; cfg.test_ds=None
    model=cls.restore_from(str(archive),override_config_path=cfg,map_location=torch.device('cpu')).eval()
    runtime=Runtime(args.model_dir,4)
    token_mapping=model.tokenizer.ids_to_tokens(list(range(len(runtime.vocabulary))))
    if token_mapping != runtime.vocabulary:
        mismatches=[{'id':i,'archive':a,'original_tokenizer':b}
                    for i,(a,b) in enumerate(zip(runtime.vocabulary,token_mapping)) if a!=b]
        raise AssertionError(f'Original tokenizer remapped archived vocabulary: {mismatches}')
    comparisons=[]
    for wav in args.wav:
        audio=read_audio(wav); waveform=torch.from_numpy(audio[None]); length=torch.tensor([len(audio)])
        features,feature_lengths=runtime.frontend(audio)
        with torch.no_grad():
            reference_features,reference_lengths=model.preprocessor(input_signal=waveform,length=length)
            result=model(input_signal=waveform,input_signal_length=length)
        ref_logits,ref_lengths=result[:2]
        logits,encoded=runtime.session.run(None,{'features':features,'feature_lengths':feature_lengths})
        np.testing.assert_array_equal(feature_lengths,reference_lengths.numpy())
        np.testing.assert_allclose(features,reference_features.numpy(),atol=3e-3,rtol=1e-3)
        np.testing.assert_array_equal(encoded,ref_lengths.numpy())
        np.testing.assert_allclose(logits,ref_logits.numpy(),atol=5e-3,rtol=1e-3)
        # Execute NeMo's actual configured CTC decoding strategy and tokenizer,
        # rather than reconstructing its collapse operation in this validator.
        with torch.inference_mode():
            reference_texts,_=model.decoding.ctc_decoder_predictions_tensor(
                decoder_outputs=ref_logits,decoder_lengths=ref_lengths,return_hypotheses=False)
        ref_text=reference_texts[0]
        text=decode(logits[0],encoded[0],runtime.vocabulary)
        if text!=ref_text: raise AssertionError(f'Tokenizer transcript mismatch: {text!r} != {ref_text!r}')
        comparisons.append({'wav':str(wav),'wav_sha256':hashlib.sha256(wav.read_bytes()).hexdigest(),
            'transcript':text,'frontend_max_absolute_error':float(np.max(np.abs(features-reference_features.numpy()))),
            'log_probs_max_absolute_error':float(np.max(np.abs(logits-ref_logits.numpy()))),
            'argmax_equal':bool(np.array_equal(logits.argmax(-1),ref_logits.numpy().argmax(-1)))})
    report={'status':'pass','complete_original_nemo_wrapper_validated':True,
        'nemo_toolkit':importlib.metadata.version('nemo_toolkit'),'torch':torch.__version__,
        'transformers':importlib.metadata.version('transformers'),
        'tokenizers':importlib.metadata.version('tokenizers'),
        'archived_vocabulary_mapping_equal':True,
        'original_configured_ctc_decoder_executed':True,
        'checkpoint_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
        'model_sha256':hashlib.sha256((args.model_dir/'model.onnx').read_bytes()).hexdigest(),
        'tokenizer_sha256':hashlib.sha256((args.model_dir/'vocab.txt').read_bytes()).hexdigest(),
        'decoder_id':hashlib.sha256((Path(__file__).parent/'citrinet_cpu.py').read_bytes()).hexdigest(),
        'preprocessing_id':hashlib.sha256((hashlib.sha256((args.model_dir/'frontend.npz').read_bytes()).hexdigest()+
                hashlib.sha256((Path(__file__).parent/'citrinet_cpu.py').read_bytes()).hexdigest()).encode()).hexdigest(),
        'frontend_npz_sha256':hashlib.sha256((args.model_dir/'frontend.npz').read_bytes()).hexdigest(),
        'frontend_constants_sha256':hashlib.sha256((args.model_dir/'frontend.npz').read_bytes()).hexdigest(),
        'frontend_source_sha256':hashlib.sha256((Path(__file__).parent/'citrinet_cpu.py').read_bytes()).hexdigest(),
        'decoder_sha256':hashlib.sha256((Path(__file__).parent/'citrinet_cpu.py').read_bytes()).hexdigest(),
        'citrinet_cpu_source_sha256':hashlib.sha256((Path(__file__).parent/'citrinet_cpu.py').read_bytes()).hexdigest(),
        'validate_nemo_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'model_config_sha256':hashlib.sha256((args.checkpoint_dir/'model_config.yaml').read_bytes()).hexdigest(),
        'tests':comparisons}
    args.output.write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps(report,indent=2))


if __name__=='__main__': main()
