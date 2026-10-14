"""Summarize user-supplied physical reports; never generate board measurements."""
import hashlib
import json
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    reports=ROOT/'reports'
    names=['cpu-experiment-board.json','hybrid-experiment-board.json','physical-experiment-board.json','native-experiment-board.json']
    cpu,hybrid,physical,native=[json.loads((reports/n).read_text()) for n in names]
    old=json.loads((reports/'board_received/2026-10-09_reference/summary.json').read_text())
    rows=[]
    for run in hybrid['runs']:
        fallback=sum(p['seconds'] for p in run['partition_profile'] if p['kind']=='cpu')
        pointwise=sum(p['seconds'] for p in run['partition_profile'] if p['kind']=='fpga')
        dma=run['dma']
        phases={k:dma[k] for k in ['ioctl_seconds','load_pack_seconds','scan_seconds','run_pack_seconds','unpack_seconds']}
        rows.append({'total_seconds':run['total_seconds'],'cpu_fallback_seconds':fallback,
                     'pointwise_seconds':pointwise,'outside_ioctl_seconds':pointwise-dma['ioctl_seconds'],
                     'other_seconds':run['total_seconds']-fallback-pointwise,
                     'unattributed_pointwise_seconds':pointwise-sum(phases.values()),**phases})
    metrics={k:{'median':statistics.median(r[k] for r in rows),'min':min(r[k] for r in rows),
                 'max':max(r[k] for r in rows)} for k in rows[0]}
    target=.8*cpu['p50_seconds']
    # Use one real run near p50 for disjoint counterfactual accounting; separate
    # component medians do not necessarily add to the median total.
    median_run=min(rows,key=lambda r:abs(r['total_seconds']-hybrid['p50_seconds']))
    floors={'free_all_pointwise':median_run['total_seconds']-median_run['pointwise_seconds'],
            'free_ioctl':median_run['total_seconds']-median_run['ioctl_seconds'],
            'free_outside_ioctl':median_run['total_seconds']-median_run['outside_ioctl_seconds'],
            'free_cpu_fallback':median_run['total_seconds']-median_run['cpu_fallback_seconds']}
    summary={'origin':'User-supplied KV260 reports; not independently run by this agent',
             'input_sha256':{n:sha(reports/n) for n in names},'cpu_p50_seconds':cpu['p50_seconds'],
             'cpu_p95_seconds':cpu['p95_seconds'],'hybrid_p50_seconds':hybrid['p50_seconds'],
             'hybrid_p95_seconds':hybrid['p95_seconds'],'warmups':[cpu['warmups'],hybrid['warmups']],
             'measured_runs':[len(cpu['runs']),len(hybrid['runs'])],
             'hybrid_to_cpu_p50_ratio':hybrid['p50_seconds']/cpu['p50_seconds'],
             'hybrid_latency_reduction_from_previous':1-hybrid['p50_seconds']/old['fpga_p50_seconds'],
             'previous_comparison_limits':'Earlier test had one warmup/three runs; no matched clock/thermal provenance',
             'target_p50_seconds':target,'additional_saving_required_seconds':hybrid['p50_seconds']-target,
             'transcripts_match':len({r['transcript'] for r in cpu['runs']+hybrid['runs']})==1,
             'physical_implementation_parity':physical['physical_vs_numerical_int8_implementation_parity'],
             'native_smoke_checks':native['checks'],'phase_statistics':metrics,
             'near_p50_disjoint_run':median_run,'conditional_floors_seconds':floors,
             'speedup_target_achieved':False,
             'limitations':['Single reference clip','CPU and hybrid measured in separate blocks, not paired/interleaved',
                            'No attached corpus WER, sustained capture, thermal or active firmware/clock evidence']}
    (reports/'experiment_analysis.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ['native_smoke_checks','input_sha256']},indent=2))

if __name__=='__main__':main()
