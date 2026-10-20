"""Render complete physical paired reports without hiding regressions."""
import argparse,json
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reports',type=Path,nargs='+',required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();lines=['# Physical FPGA paired measurements','',
        'Warm timing includes WAV reading, the original frontend, one graph and decoding.',
        'CPU uses the fastest tested INT8 graph with four non-spinning threads.',
        'Negative savings and slower tail latency are retained. These clips are not a representative corpus.','']
    for path in args.reports:
        d=json.loads(path.read_text());assert d['complete'] and d['hardware_execution']
        lines += [f'## {path.name} ({d["runs"]} pairs per recording)','',
            '| Recording | CPU p50 (ms) | FPGA p50 (ms) | CPU p95 (ms) | FPGA p95 (ms) | Mean-saving 95% CI (ms) | CPU/FPGA errors |',
            '| --- | ---: | ---: | ---: | ---: | --- | --- |']
        for c in d['clips']:
            assert c['physical_oracle_bit_parity']
            lo,hi=c['mean_saving_95ci_seconds']
            lines.append(f'| {c["id"]} | {c["cpu_p50"]*1000:.3f} | {c["fpga_p50"]*1000:.3f} | {c["cpu_p95"]*1000:.3f} | {c["fpga_p95"]*1000:.3f} | {lo*1000:.3f} to {hi*1000:.3f} | {c["cpu_errors"]}/{c["fpga_errors"]} |')
        if d.get('reference_is_model_prediction_not_human_ground_truth'):
            lines += ['', 'Original-reference error counts compare against a model prediction, not human ground truth; no WER accuracy claim is made.']
        else:
            ce=sum(c['cpu_errors'] for c in d['clips']);fe=sum(c['fpga_errors'] for c in d['clips']);words=sum(c['reference_words'] for c in d['clips'])
            lines += ['',f'Available reference errors: CPU {ce}/{words}; FPGA {fe}/{words}.']
        lines += ['']
    lines += ['Representative WER and sustained microphone capture remain unvalidated. The application preserves a CPU-only command for short clips.','']
    args.out.write_text('\n'.join(lines))
if __name__=='__main__':main()
