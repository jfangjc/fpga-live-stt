#!/usr/bin/env python3
"""Offline STT latency benchmark for the KV260.

Each model runs in its own child process, so peak memory is measured per model.

    python3 bench.py                                  # every model in models.MODELS
    python3 bench.py --models moonshine-tiny quartznet15x5
"""
import argparse
import csv
import glob
import json
import re
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
SR = 16000


def load_clips(data_dir):
    clips = []
    with open(data_dir / "manifest.tsv", encoding="utf-8") as f:
        for line in f:
            clip_id, ref = line.rstrip("\n").split("\t", 1)
            audio, sr = sf.read(data_dir / f"{clip_id}.wav", dtype="float32")
            assert sr == SR, f"{clip_id}: expected {SR} Hz, got {sr}"
            clips.append((clip_id, audio, ref))
    return clips


def normalize(text):
    text = re.sub(r"[^a-z' ]", " ", text.lower())
    return " ".join(text.split())


def cpu_temp_c():
    temps = []
    for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        try:
            temps.append(int(Path(path).read_text()) / 1000)
        except (OSError, ValueError):
            pass
    return max(temps) if temps else float("nan")


def bench_model(name, args):
    import jiwer

    sys.path.insert(0, str(HERE))
    from models import MODELS

    clips = load_clips(args.data)

    t0 = time.perf_counter()
    model = MODELS[name](args.threads)
    load_s = time.perf_counter() - t0

    for _, audio, _ in clips[: args.warmup]:
        model.transcribe(audio)

    rows = []
    args.out.mkdir(parents=True, exist_ok=True)
    progress_path = args.out / f'{name}.progress.json'
    progress_path.write_text(json.dumps({'state': 'measuring', 'completed': 0, 'total': len(clips), 'load_s': load_s}))
    for clip_id, audio, ref in clips:
        t0 = time.perf_counter()
        hyp = model.transcribe(audio)
        proc_s = time.perf_counter() - t0
        audio_s = len(audio) / SR
        rows.append(
            {
                "model": name,
                "clip": clip_id,
                "audio_s": round(audio_s, 3),
                "proc_s": round(proc_s, 4),
                "rtf": round(proc_s / audio_s, 4),
                "temp_c": cpu_temp_c(),
                "ref": ref,
                "hyp": hyp,
            }
        )
        print(f"  {name:<18} {clip_id:<20} {audio_s:5.1f}s audio -> {proc_s:6.2f}s", flush=True)
        progress_path.write_text(json.dumps({'state': 'measuring', 'completed': len(rows), 'total': len(clips), 'latest': rows[-1]}))

    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KiB on Linux
    lat = np.array([r["proc_s"] for r in rows])
    summary = {
        "model": name,
        "clips": len(rows),
        "load_s": round(load_s, 2),
        "latency_p50_s": round(float(np.percentile(lat, 50)), 3),
        "latency_p90_s": round(float(np.percentile(lat, 90)), 3),
        "latency_max_s": round(float(lat.max()), 3),
        "rtf": round(sum(r["proc_s"] for r in rows) / sum(r["audio_s"] for r in rows), 3),
        "wer": round(jiwer.wer([normalize(r["ref"]) for r in rows], [normalize(r["hyp"]) for r in rows]), 4),
        "peak_rss_mb": round(peak_rss_mb),
        "max_temp_c": max(r["temp_c"] for r in rows),
    }

    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.out / f"{name}.json").write_text(json.dumps(summary, indent=2))
    progress_path.write_text(json.dumps({'state': 'complete', **summary}))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", help="subset of models.MODELS (default: all)")
    parser.add_argument("--data", type=Path, default=HERE / "data")
    parser.add_argument("--out", type=Path, default=HERE / "results")
    parser.add_argument("--threads", type=int, default=4, help="CPU threads per model (KV260 has 4 A53 cores)")
    parser.add_argument("--warmup", type=int, default=2, help="untimed clips run before measuring")
    parser.add_argument("--cooldown", type=float, default=30, help="seconds to idle between models")
    parser.add_argument("--child", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.child:
        bench_model(args.child, args)
        return

    sys.path.insert(0, str(HERE))
    from models import MODELS

    names = args.models or list(MODELS)
    unknown = set(names) - set(MODELS)
    if unknown:
        parser.error(f"unknown models: {', '.join(sorted(unknown))}")

    summaries = []
    for i, name in enumerate(names):
        if i and args.cooldown:
            time.sleep(args.cooldown)
        print(f"== {name} (start temp {cpu_temp_c():.0f} C)", flush=True)
        cmd = [sys.executable, __file__, "--child", name, "--data", str(args.data), "--out", str(args.out),
               "--threads", str(args.threads), "--warmup", str(args.warmup)]
        if subprocess.run(cmd).returncode != 0:
            print(f"!! {name} failed, skipping", flush=True)
            continue
        summaries.append(json.loads((args.out / f"{name}.json").read_text()))

    if not summaries:
        sys.exit("no model finished")

    with open(args.out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)

    print(f"\n{'model':<18} {'load s':>7} {'p50 s':>7} {'p90 s':>7} {'RTF':>6} {'WER':>6} {'RSS MB':>7} {'max C':>6}")
    for s in summaries:
        print(f"{s['model']:<18} {s['load_s']:>7.2f} {s['latency_p50_s']:>7.3f} {s['latency_p90_s']:>7.3f} "
              f"{s['rtf']:>6.3f} {s['wer']:>6.1%} {s['peak_rss_mb']:>7} {s['max_temp_c']:>6.0f}")
    print(f"\nPer-clip results and summary.csv in {args.out}")


if __name__ == "__main__":
    main()
