"""Sequential isolated model processes, with durable copies after each model."""
import csv
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models import MODELS
parser = argparse.ArgumentParser()
parser.add_argument('--models', nargs='+', choices=list(MODELS))
parser.add_argument('--initial-cooldown', type=float, default=0)
parser.add_argument('--out', type=Path, default=HERE / 'results')
args = parser.parse_args()
names = args.models or list(MODELS)

OUT = args.out.resolve()
RAM = Path('/dev/shm/kv260-stt-results')
OUT.mkdir(parents=True, exist_ok=True)
RAM.mkdir(exist_ok=True)
os.environ.update(OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4', HF_HUB_OFFLINE='1', HF_HUB_DISABLE_PROGRESS_BARS='1', TOKENIZERS_PARALLELISM='false')
status = json.loads((OUT / 'status.json').read_text()) if (OUT / 'status.json').exists() else []
summaries = [json.loads((OUT / f'{row["model"]}.json').read_text()) for row in status if row['returncode'] == 0]
if args.initial_cooldown:
    time.sleep(args.initial_cooldown)
for i, name in enumerate(names):
    if i:
        print('Cooling down for 30 seconds', flush=True)
        time.sleep(30)
    started = time.time()
    print(f'== {i + 1}/{len(names)} {name}', flush=True)
    with (OUT / f'{name}.log').open('w') as log:
        result = subprocess.run([sys.executable, '-u', str(HERE / 'bench.py'), '--child', name,
                                 '--data', str(HERE / 'data'), '--out', str(RAM), '--threads', '4', '--warmup', '2'],
                                stdout=log, stderr=subprocess.STDOUT)
    row = {'model': name, 'returncode': result.returncode, 'wall_s': round(time.time() - started, 2)}
    for path in RAM.glob(name + '.*'):
        shutil.copy2(path, OUT / path.name)
    if result.returncode == 0:
        summary = json.loads((OUT / f'{name}.json').read_text())
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
    else:
        print(f'FAILED {name}: exit {result.returncode}', flush=True)
        print((OUT / f'{name}.log').read_text()[-4000:], flush=True)
    status.append(row)
    (OUT / 'status.json').write_text(json.dumps(status, indent=2))
    if summaries:
        with (OUT / 'summary.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(summaries[0]))
            writer.writeheader()
            writer.writerows(summaries)
print('SUITE COMPLETE', flush=True)
