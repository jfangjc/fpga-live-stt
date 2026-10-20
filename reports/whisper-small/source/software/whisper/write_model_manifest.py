"""Verify the upstream FP16 checkpoint and bind locally quantized comparators."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from benchmark import check_model, sha
from model_spec import SPECS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=Path.cwd())
    parser.add_argument('--model', choices=SPECS, default='large-v3-turbo')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Refusing to overwrite model provenance')
    spec = SPECS[args.model]
    source = args.work/'models'/f'ggml-{args.model}.bin'
    with source.open('rb') as stream:
        source_sha1 = hashlib.file_digest(stream,'sha1').hexdigest()
    if source_sha1!=spec['source_sha1']:
        raise ValueError('Upstream checkpoint SHA1 mismatch')
    entries = {}
    for suffix in ('','-q8_0','-q5_0'):
        path = source.with_name(f'ggml-{args.model}{suffix}.bin')
        if check_model(path)!=spec['id']:
            raise ValueError('Quantized model architecture mismatch')
        with path.open('rb') as stream:
            header = struct.unpack('<12i',stream.read(48))
        entries[str(path.relative_to(args.work))] = {'sha256':sha(path), 'bytes':path.stat().st_size,
                                                    'ggml_header':header}
    quantizer = args.work/'build-cpu/bin/whisper-quantize'
    result = {'model':spec['id'], 'source_sha1':source_sha1,
              'source_url':f'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{args.model}.bin',
              'upstream_commit':'2eeeba56e9edd762b4b38467bab96c2517163158',
              'quantizer_sha256':sha(quantizer), 'models':entries}
    args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
