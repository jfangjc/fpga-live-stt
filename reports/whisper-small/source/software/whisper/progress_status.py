"""Read qualification progress without touching accelerator state."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',required=True,type=Path)
    args = parser.parse_args()
    state = json.loads((args.work/'pipeline_state.json').read_text())
    result = {key:state[key] for key in ('status','phase','total_runs')}
    progress = args.work/f'{"validation" if state["phase"]=="accuracy" else "latency"}_progress.jsonl'
    if state['phase'] in ('accuracy','latency') and progress.exists():
        rows = []
        for line in progress.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
        result['completed_runs'] = sum('seconds' in row for row in rows)
        if rows:
            result['last_variant'] = rows[-1].get('variant')
            result['clip'] = Path(rows[-1].get('clip','')).name
    result['phase_elapsed_minutes'] = round((datetime.now().astimezone()-datetime.fromisoformat(state['phase_started'])).total_seconds()/60,1)
    cpu = subprocess.run(['ps','-C','whisper-cli','-o','etime=,pcpu=,rss='],capture_output=True,text=True)
    if cpu.stdout.strip():
        elapsed,utilization,rss = cpu.stdout.strip().split()[:3]
        result['current_cli'] = {'elapsed':elapsed,'cpu_percent':float(utilization),'resident_mib':round(int(rss)/1024)}
    if 'error' in state:
        result['error'] = state['error']
    print(json.dumps(result))


if __name__ == '__main__':
    main()
