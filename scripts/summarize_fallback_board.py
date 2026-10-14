"""Summarize user-supplied CPU-only fallback probes, not FPGA acceptance."""
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    rows=[]
    for label in ['per1','shared1','shared2','shared4']:
        path=ROOT/'reports'/f'regions-{label}-board.json'
        data=json.loads(path.read_text())
        expected={name:sha(ROOT/name.replace('\\','/')) for name in data['sources_sha256']}
        assert expected==data['sources_sha256'],f'Changed source: {label}'
        assert data['model_sha256']==sha(ROOT/'research/export/citrinet-256-ls/model.onnx')
        assert data['wav_sha256']==sha(ROOT/'research/reference_speech.wav')
        assert data['fp32_output_parity_passed'] is True and data['hardware_execution'] is False
        assert data['warmups']==3 and len(data['runs'])==20
        for metric in ['full_cpu_graph_seconds','partition_seconds','cpu_region_seconds','fp32_pointwise_seconds']:
            values=[r[metric] for r in data['runs']]
            assert np.all(np.isfinite(values)) and min(values)>0
            for pct in [50,95]:
                assert np.isclose(np.percentile(values,pct),data[f'{metric}_p{pct}'],rtol=0,atol=1e-12)
        rows.append({'file':path.name,'sha256':sha(path),'pool':data['pool'],'threads':data['threads'],
                     'parity_passed':True,'runs':len(data['runs']),
                     **{k:v for k,v in data.items() if k.endswith(('_p50','_p95'))}})
    base=rows[0]
    for row in rows:
        row['fallback_p50_reduction_vs_per1']=1-row['cpu_region_seconds_p50']/base['cpu_region_seconds_p50']
    baseline_path=next(p for p in [ROOT/'reports/cpu-experiment-board.json',
                                  ROOT/'reports/old/cpu-experiment-board.json'] if p.is_file())
    current_cpu=json.loads(baseline_path.read_text())['p50_seconds']
    target=.8*current_cpu
    summary={'origin':'User-supplied KV260 CPU-only probes','integrity_checks_passed':True,'settings':rows,
             'processing_baseline_file':str(baseline_path.relative_to(ROOT)),
             'processing_baseline_sha256':sha(baseline_path),
             'current_processing_target_p50_seconds':target,
             'best_fallback_configuration':'shared2','best_fallback_p50_seconds':rows[2]['cpu_region_seconds_p50'],
             'best_fallback_alone_exceeds_processing_target':rows[2]['cpu_region_seconds_p50']>target,
             'production_thread_policy_changed':False,
             'conclusion':'Thread-only tuning is insufficient; no whole physical hybrid improvement demonstrated',
             'limits':['FP32 CPU pointwise control, not physical FPGA execution',
                       'Complete graph thread count changes with each setting; controls are not a fixed optimized CPU baseline',
                       'No clock/thermal/scheduler traces; increased pointwise time cannot be assigned conclusively to worker spinning']}
    (ROOT/'reports/fallback_analysis.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
