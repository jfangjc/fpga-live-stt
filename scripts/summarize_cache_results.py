"""Bind four-pair physical results and compute explicit latency decision gates."""
import json
from pathlib import Path
import hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
R=ROOT/'reports/fused'
def read(name):return json.loads((R/name).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    validation=read('cache_physical_validation.json');resident=read('cache_resident_validation.json')
    assert validation['complete'] and validation['hardware_execution'] and resident['complete']
    assert len(validation['clips'])==36 and all(r['physical_oracle_bit_parity'] and r['length_exact'] for r in validation['clips'])
    assert validation['errors']['cpu']==validation['errors']['fpga']==validation['errors']['oracle']
    summary=[];lines=['# Four-pair FPGA physical results','',
                     'Eight convolutions execute on FPGA as four retained DW11/PW pairs. '
                     'Masking and requantization between the convolutions stay on FPGA. '
                     'Other activation, residual and SE operations remain on CPU.','',
                     '| Scope / input | CPU p50 ms | FPGA p50 ms | CPU p95 ms | FPGA p95 ms | Gate |',
                     '| --- | ---: | ---: | ---: | ---: | --- |']
    bindings={n:sha(R/n) for n in ('cache_physical_validation.json','cache_resident_validation.json')}
    for kind in ('block','total'):
        for label in ('half','one'):
            name=f'cache_{kind}_{label}.json';report=read(name)
            assert report['complete'] and report['hardware_execution']
            assert report['library_sha256']==validation['library_sha256']
            metric=report if kind=='block' else report['contexts'][0];rows=report['paired_runs']
            assert len(rows)==report['runs'] and report['runs']>=(200 if kind=='block' else 300)
            if kind=='total':
                for key in ('driver_sha256','firmware_sha256'):
                    assert report[key]==validation[key]
                assert report['validation_sha256']==sha(R/'cache_physical_validation.json')
                assert report['fpga_graph_sha256']==sha((R/name).with_suffix('.onnx'))
            c=np.array([row['seconds']['cpu'] if kind=='block' else row['results']['cpu']['seconds'] for row in rows])
            f=np.array([row['seconds']['fpga'] if kind=='block' else row['results']['fpga']['seconds'] for row in rows])
            assert np.all(np.isfinite(c)) and np.all(c>0) and np.all(np.isfinite(f)) and np.all(f>0)
            audited={'cpu_p50':np.median(c),'fpga_p50':np.median(f),
                     'cpu_p95':np.percentile(c,95),'fpga_p95':np.percentile(f,95),
                     'mean_saving_95ci_seconds':np.percentile(np.random.default_rng(11102026).choice(c-f,(10000,len(c)),replace=True).mean(axis=1),[2.5,97.5])}
            for key,value in audited.items():
                np.testing.assert_allclose(metric[key],value,rtol=0,atol=1e-12)
            for row in rows:
                counters=row['counters'] if kind=='block' else row['results']['fpga']['counters']
                expected=1 if kind=='block' else 4
                assert counters['loads']==0 and counters['ioctls']==expected
                assert counters['physical_calls']==expected and counters['oracle_calls']==0
            lower,upper=metric['mean_saving_95ci_seconds']
            accepted=metric['fpga_p50']<metric['cpu_p50'] and metric['fpga_p95']<=metric['cpu_p95'] and lower>0
            entry={'scope':kind,'context_seconds':metric.get('context_seconds',report.get('context_seconds')),
                   **{k:metric[k] for k in ('cpu_p50','fpga_p50','cpu_p95','fpga_p95','mean_saving_95ci_seconds')},
                   'runs':report['runs'],'latency_gate_passed':accepted,
                   'p50_reduction_percent':100*(1-metric['fpga_p50']/metric['cpu_p50'])}
            summary.append(entry);bindings[name]=sha(R/name)
            lines.append(f"| {kind} / {entry['context_seconds']:g} s | {metric['cpu_p50']*1000:.3f} | {metric['fpga_p50']*1000:.3f} | {metric['cpu_p95']*1000:.3f} | {metric['fpga_p95']*1000:.3f} | {'pass' if accepted else 'not accepted'} |")
    all_total=all(r['latency_gate_passed'] for r in summary if r['scope']=='total')
    lines+=['','The gate requires lower FPGA p50, non-regressing measured p95, and a positive '
            'lower bound on the paired mean-saving 95% confidence interval. Transfers, '
            'synchronization, frontend and decoding are included in total latency.','']
    for row in summary:
        if row['scope']=='total':
            lo,hi=row['mean_saving_95ci_seconds']
            lines.append(f"- {row['context_seconds']:g} s: mean-saving 95% CI {lo*1000:.3f} to {hi*1000:.3f} ms, {row['runs']} paired runs.")
    lines+=['',f"Diagnostic correctness: all 36 full/prefix cases match the native oracle bit-for-bit. Full clips retain {validation['errors']['cpu']} errors across {validation['words']} reference words in both CPU and FPGA paths. Representative WER qualification remains pending.",'',
            'The resident API passed transcript/length parity and four physical calls with zero warm weight loads. Capture remains deferred.','',
            f"Whole-model latency gate for both measured contexts: {'passed' if all_total else 'not accepted'}. No promotion is implied by a component speed result."]
    report={'complete':True,'hardware_execution':True,'accelerated_convolutions':8,'retained_pairs':4,
            'whole_model_latency_accepted':all_total,'metrics':summary,'evidence_sha256':bindings,
            'source_sha256':sha(Path(__file__)),'representative_corpus_qualified':False,'capture_tested':False}
    report['raw_paired_statistics_independently_recomputed']=True
    (R/'cache_result_summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    (ROOT/'CACHE_RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'whole_model_latency_accepted':all_total,'metrics':summary}))


if __name__=='__main__':main()
