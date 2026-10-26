#!/usr/bin/env python3
"""Pick a fixed random subset of LibriSpeech test-clean and write 16 kHz WAVs + manifest.tsv.

    python3 prepare_data.py ~/LibriSpeech/test-clean --n 40
"""
import argparse
import random
from pathlib import Path

import soundfile as sf

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("librispeech_dir", type=Path, help="e.g. LibriSpeech/test-clean")
    parser.add_argument("--out", type=Path, default=HERE / "data")
    parser.add_argument("--n", type=int, default=40)
    parser.add_argument("--min-s", type=float, default=2.0)
    parser.add_argument("--max-s", type=float, default=20.0, help="keep under Whisper's 30 s window")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    utts = []
    for trans in sorted(args.librispeech_dir.rglob("*.trans.txt")):
        for line in trans.read_text(encoding="utf-8").splitlines():
            utt_id, text = line.split(" ", 1)
            utts.append((utt_id, text, trans.parent / f"{utt_id}.flac"))

    random.Random(args.seed).shuffle(utts)
    args.out.mkdir(parents=True, exist_ok=True)
    picked = []
    for utt_id, text, flac in utts:
        info = sf.info(flac)
        if not args.min_s <= info.duration <= args.max_s:
            continue
        audio, sr = sf.read(flac, dtype="float32")
        assert sr == 16000
        sf.write(args.out / f"{utt_id}.wav", audio, sr, subtype="PCM_16")
        picked.append((utt_id, text))
        if len(picked) == args.n:
            break

    with open(args.out / "manifest.tsv", "w", encoding="utf-8") as f:
        for utt_id, text in picked:
            f.write(f"{utt_id}\t{text}\n")
    print(f"wrote {len(picked)} clips to {args.out}")


if __name__ == "__main__":
    main()
