"""Run the isolated, measured CPU INT8 candidate with the original frontend."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
import onnxruntime as ort
from common import ROOT, Frontend, read_audio, decode, identity, sha, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wav', type=Path, nargs='+')
    parser.add_argument('--model-dir', type=Path, default=ROOT/'research/export/citrinet-256-ls')
    parser.add_argument('--candidate-model', type=Path, default=ROOT/'research/fused/cpu-int8.onnx')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.threads < 1:
        parser.error('--threads must be positive')
    proof = json.loads(args.candidate_model.with_suffix('.json').read_text())
    candidate_sha = sha(args.candidate_model)
    if proof['source_identity'] != identity(args.model_dir) or proof['model_sha256'] != candidate_sha:
        raise ValueError('Candidate model/frontend/decoder identity mismatch')
    opt = ort.SessionOptions()
    opt.intra_op_num_threads = args.threads
    opt.inter_op_num_threads = 1
    opt.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opt.add_session_config_entry('session.intra_op.allow_spinning','0')
    opt.add_session_config_entry('session.inter_op.allow_spinning','0')
    start = time.perf_counter()
    runner = ort.InferenceSession(str(args.candidate_model), opt, providers=['CPUExecutionProvider'])
    frontend = Frontend(args.model_dir)
    vocab = (args.model_dir/'vocab.txt').read_text().splitlines()
    initialization = time.perf_counter()-start
    records = []
    for path in args.wav:
        start = time.perf_counter()
        audio = read_audio(path)
        features, lengths = frontend(audio)
        logits, encoded = runner.run(None,{'features':features,'feature_lengths':lengths})
        if not np.all(np.isfinite(logits)) or not 0 <= int(encoded[0]) <= logits.shape[1]:
            raise ValueError('Invalid logits or encoded output length')
        transcript = decode(logits[0],encoded[0],vocab)
        records.append({'wav':str(path.resolve()),'text':transcript,
                        'encoded_length':int(encoded[0]),
                        'processing_seconds':time.perf_counter()-start})
        print(transcript,flush=True)
    report = {'execution':'CPU INT8; no FPGA execution','candidate_sha256':candidate_sha,
              'threads':args.threads,'worker_spinning':False,
              'initialization_seconds':initialization,'recordings':records,
              'representative_accuracy_accepted':False}
    if args.out:
        write_json(args.out,report)


if __name__ == '__main__':
    main()
