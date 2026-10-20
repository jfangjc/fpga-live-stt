"""Isolated Whisper board transport. Set ASR_KV260_PASSWORD in the environment."""
import argparse
import os
from pathlib import Path
import subprocess

HOST = 'ubuntu@192.168.1.111'
KEY = 'SHA256:LKipAYiol8maTkeoe4VDOwZRuJLRLhyp1Nd7iSMk+1I'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['exec', 'upload', 'download'])
    parser.add_argument('source')
    parser.add_argument('destination', nargs='?')
    args = parser.parse_args()
    password = os.environ['ASR_KV260_PASSWORD']
    common = ['-batch', '-hostkey', KEY, '-pw', password]
    if args.action == 'exec':
        command = ['C:/Program Files/PuTTY/plink.exe', *common, HOST, args.source]
    else:
        if not args.destination:
            parser.error('file transfers require a destination')
        source, destination = args.source, args.destination
        if args.action == 'upload':
            source = str(Path(source).resolve())
            destination = HOST + ':' + destination
        else:
            source = HOST + ':' + source
        command = ['C:/Program Files/PuTTY/pscp.exe', *common, source, destination]
    raise SystemExit(subprocess.run(command).returncode)


if __name__ == '__main__':
    main()
