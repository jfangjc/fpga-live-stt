"""Fetch requested public LS checkpoints at pinned, SHA256-verified revisions."""
import argparse, hashlib, json, re, shutil, tarfile, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser(); p.add_argument('--sizes', nargs='+', type=int, default=[512,1024]); a=p.parse_args()
    for size in a.sizes:
        assert size in (512,1024)
        repo=f'nvidia/stt_en_citrinet_{size}_ls'; name=f'stt_en_citrinet_{size}_ls.nemo'
        if size==1024:
            # NVIDIA's 1024-LS repository contains a card but no checkpoint.
            repo='nvidia/stt_en_citrinet_1024_gamma_0_25'; name='stt_en_citrinet_1024_gamma_0_25.nemo'
        directory=ROOT/f'research/checkpoints/citrinet-{size}-ls'; directory.mkdir(parents=True,exist_ok=True)
        proof_path=directory/'acquisition.json'
        if proof_path.exists():
            metadata=json.loads(proof_path.read_text()); revision=metadata['revision']; expected=metadata['sha256']
        else:
            with urllib.request.urlopen(f'https://huggingface.co/api/models/{repo}?blobs=true', timeout=60) as r: info=json.load(r)
            revision=info['sha']; file=next(f for f in info['siblings'] if f['rfilename']==name)
            expected=file['lfs']['sha256']
            metadata={'repository':repo,'revision':revision,'sha256':expected,'bytes':file['lfs']['size']}
            proof_path.write_text(json.dumps(metadata,indent=2)+'\n')
        path=directory/name
        if not path.exists():
            temporary=path.with_suffix('.partial')
            print(f'Downloading {repo} revision {revision}',flush=True)
            with urllib.request.urlopen(f'https://huggingface.co/{repo}/resolve/{revision}/{name}',timeout=120) as src,temporary.open('wb') as dst: shutil.copyfileobj(src,dst,1024*1024)
            temporary.replace(path)
        digest=hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
        if digest!=expected: raise ValueError(f'{name}: SHA256 mismatch')
        with tarfile.open(path) as archive:
            for member in archive:
                clean=member.name.removeprefix('./')
                if member.isdir() and clean in ('','.'): continue
                allowed=clean in {'model_config.yaml','model_weights.ckpt','vocab.txt','tokenizer.model','tokenizer.vocab'} or re.fullmatch(r'[0-9a-f]{32}_(tokenizer.model|vocab.txt|tokenizer.vocab)',clean)
                if not allowed or not member.isfile():
                    raise ValueError(f'Unexpected checkpoint member: {member.name}')
                with archive.extractfile(member) as src,(directory/clean).open('wb') as dst: shutil.copyfileobj(src,dst)
        print(json.dumps(metadata),flush=True)

if __name__=='__main__': main()
