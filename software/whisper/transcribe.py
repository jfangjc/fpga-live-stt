"""Transcribe a WAV with a supported multilingual Whisper model and real DMA evidence."""
import argparse
import json
from pathlib import Path
from benchmark import check_model, run, sha, dependencies


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('audio', type=Path)
    ap.add_argument('--binary', required=True, type=Path)
    ap.add_argument('--model', required=True, type=Path)
    ap.add_argument('--mode', choices=['cpu', 'hybrid'], default='hybrid')
    ap.add_argument('--language', default='auto')
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--fpga-decoder', action='store_true')
    ap.add_argument('--fpga-attention', action='store_true')
    ap.add_argument('--flash-attention', action='store_true')
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args()
    if a.out.suffix.lower()!='.json':
        ap.error('--out must end in .json')
    identity = check_model(a.model)
    log = a.out.with_suffix('.log')
    if a.out.exists() or log.exists():
        ap.error('Refusing to overwrite transcript or log')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    result = run(a.binary,a.model,a.audio,a.threads,a.mode=='hybrid',log,a.language,
                 a.fpga_decoder,a.fpga_attention,a.flash_attention)
    result.update({'language': a.language, 'mode': a.mode, 'model': identity,
                   'timing_scope': 'Full process including model load and file I/O',
                   'dynamic_libraries':dependencies(a.binary),
                   'sha256': {str(p): sha(p) for p in [a.binary,a.model,a.audio]}})
    a.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
