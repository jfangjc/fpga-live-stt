"""Summarize recorded paired timings and FPGA counters without rerunning tests."""
import argparse, hashlib, json, statistics
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('report',type=Path)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
result=json.loads(args.report.read_text())
assert result['complete'] and result['hardware_execution']
clock=result['clock_hz']
contexts=[]
for context in result['contexts']:
    rows=[r['results']['fpga'] for r in context['runs']]
    median=lambda f:statistics.median(f(r) for r in rows)
    entry={k:context[k] for k in ('context_seconds','cpu_p50','fpga_p50','latency_reduction_percent')}
    entry['components_ms']={
        'frontend':median(lambda r:r['frontend_seconds'])*1000,
        'model':median(lambda r:r['model_seconds'])*1000,
        'decode':median(lambda r:r['decode_seconds'])*1000,
        'ioctl_including_transfer_compute_and_sync':median(lambda r:r['counters']['ioctl_seconds'])*1000,
        'activation_packing':median(lambda r:r['counters']['run_pack_seconds'])*1000,
        'output_unpacking':median(lambda r:r['counters']['unpack_seconds'])*1000,
        'fpga_active_including_weight_loading':median(lambda r:r['counters']['active_cycles']/clock)*1000,
        'pointwise_mac_issue':median(lambda r:r['counters']['mac_issue_cycles']/clock)*1000,
        'input_stalls':median(lambda r:r['counters']['input_stall_cycles']/clock)*1000,
        'output_stalls':median(lambda r:r['counters']['output_stall_cycles']/clock)*1000,
        'cpu_and_dispatch_remainder':median(lambda r:r['model_seconds']-sum(r['counters'][k] for k in ('ioctl_seconds','run_pack_seconds','unpack_seconds')))*1000,
    }
    entry['transferred_bytes']=median(lambda r:r['counters']['tx_bytes']+r['counters']['rx_bytes'])
    entry['additional_ms_needed_for_30_percent']=max(0,1000*(context['fpga_p50']-.7*context['cpu_p50']))
    entry['additional_ms_needed_for_50_percent']=max(0,1000*(context['fpga_p50']-.5*context['cpu_p50']))
    entry['speedup_factor']=context['cpu_p50']/context['fpga_p50']
    contexts.append(entry)
output={'complete':True,'hardware_execution':True,
        'source_report_sha256':hashlib.sha256(args.report.read_bytes()).hexdigest(),
        'notes':'Components overlap: FPGA active is inside ioctl time; each value is its own median. CPU remainder includes dispatch. These are measured costs, not projected latency gains.',
        'contexts':contexts}
args.out.parent.mkdir(parents=True,exist_ok=True)
args.out.write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps(output,indent=2))
