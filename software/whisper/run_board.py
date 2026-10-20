"""One-command physical Whisper transcription with verified application restore."""
import argparse
from pathlib import Path
import subprocess
import sys
from benchmark import check_model


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('audio',type=Path)
    ap.add_argument('--work',type=Path,default=Path.cwd())
    ap.add_argument('--release',type=Path,required=True,help='Root containing deployment/kernel-compat')
    ap.add_argument('--model',type=Path)
    ap.add_argument('--language',default='auto')
    ap.add_argument('--threads',type=int,default=4)
    ap.add_argument('--out',type=Path,required=True)
    a = ap.parse_args()
    if a.out.suffix.lower()!='.json':
        ap.error('--out must end in .json')
    root = Path(__file__).resolve().parent
    work = a.work.resolve()
    default = work/'ggml-large-v3-turbo-q8_0.bin'
    if not default.exists():
        default = work/'ggml-base-q8_0.bin'
    model = (a.model or default).resolve()
    binary = work/'build-hybrid/bin/whisper-cli'
    session = a.out.with_suffix('.session.json')
    for path in (a.audio,model,binary):
        if not path.is_file():
            ap.error(f'Missing file: {path}')
    check_model(model)
    if a.threads<1:
        ap.error('threads must be positive')
    if any(p.exists() for p in (a.out,a.out.with_suffix('.log'),session)):
        ap.error('Refusing to overwrite transcript, log or session evidence')
    command = [sys.executable,str(root/'hardware_session.py'),'--release',str(a.release.resolve()),
               '--expected-app','k26-starter-kits','--evidence',str(session.resolve()),'--',
               sys.executable,str(root/'transcribe.py'),str(a.audio.resolve()),
               '--binary',str(binary),'--model',str(model),'--language',a.language,
               '--threads',str(a.threads),'--fpga-attention','--out',str(a.out.resolve())]
    raise SystemExit(subprocess.run(command).returncode)


if __name__ == '__main__':
    main()
