#!/usr/bin/env python3
"""Acquire the exact public candidate revision with mandatory SHA256 check."""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path
import urllib.request

REVISION='c7cdacff0262bbb2a17771d20ec9f9f3b5cff6ed'
SHA256='a00c8fb75a2bcc37271275293bce950863e4e069d43f6cf193d42fcf605aa21c'
URL=f'https://huggingface.co/nvidia/stt_en_citrinet_256_ls/resolve/{REVISION}/stt_en_citrinet_256_ls.nemo'


def main():
    p=argparse.ArgumentParser(); p.add_argument('--output-dir',type=Path,required=True); a=p.parse_args()
    a.output_dir.mkdir(parents=True,exist_ok=True)
    path=a.output_dir/'stt_en_citrinet_256_ls.nemo'
    if not path.exists():
        with urllib.request.urlopen(URL) as src,path.open('wb') as dst:
            while chunk:=src.read(1024*1024): dst.write(chunk)
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    if actual!=SHA256: raise ValueError(f'Checkpoint SHA256 mismatch: {actual}')
    expected={'model_config.yaml','model_weights.ckpt','vocab.txt'}
    with tarfile.open(path) as archive:
        for member in archive.getmembers():
            name=member.name.removeprefix('./')
            if name not in expected:
                if member.isdir() and name in {'','.','/'}: continue
                raise ValueError(f'Unexpected archive member: {member.name!r}')
            if not member.isfile(): raise ValueError('Only regular files allowed')
            with archive.extractfile(member) as src,(a.output_dir/name).open('wb') as dst:
                dst.write(src.read())
    print(json.dumps({'revision':REVISION,'sha256':actual,'url':URL},indent=2))


if __name__=='__main__': main()
