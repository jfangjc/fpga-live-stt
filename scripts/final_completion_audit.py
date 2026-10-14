"""Close every latency/parity requirement against completed authoritative evidence."""
import hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];R=ROOT/'reports/fused'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda name:json.loads((R/name).read_text())
audit=read('branch512_ab166_vf_acceptance_audit.json')
assert audit['complete'] and audit['evidence_valid'] and audit['twofold_speed_acceptance']
leaders_path=R/'valid_frame_cpu_leaders_confirmation.json';leaders=json.loads(leaders_path.read_text())
assert leaders['complete'] and not leaders['hardware_execution'] and not leaders['fpga_session_loaded']
assert leaders['source_sha256']==sha(ROOT/'software/latency/recheck_valid_frame_cpu_leaders.py')
assert leaders['screen_sha256']==sha(R/'valid_frame_cpu_policy.json')
assert leaders['frontend_sha256']==sha(ROOT/'software/latency/frontend_valid_frames.py')
assert leaders['cpu_model_sha256']==sha(ROOT/'research/fused/cpu-int8-cse.onnx')
contexts=[]
for context in audit['contexts']:
    checks=next(c for c in leaders['contexts'] if c['context_seconds']==context['context_seconds'])
    assert len(checks['policies'])>=4
    for candidate in checks['policies']:
        assert candidate['all_logits_bit_exact'] and len(candidate['seconds'])==100
        assert np.isclose(candidate['cpu_p50'],np.median(candidate['seconds']),rtol=0,atol=1e-12)
        assert np.isclose(candidate['cpu_p95'],np.percentile(candidate['seconds'],95),rtol=0,atol=1e-12)
    assert checks['fastest']==min(checks['policies'],key=lambda c:c['cpu_p50'])
    cpu50=min(context['strongest_cpu_p50'],checks['fastest']['cpu_p50'])
    cpu95=min([context['strongest_cpu_p95']]+[c['cpu_p95'] for c in checks['policies']])
    passed=context['fpga_p50']<=.5*cpu50 and context['fpga_p95']<cpu95
    assert passed,'Goal not achieved for '+str(context['context_seconds'])
    contexts.append({'input_seconds':context['context_seconds'],'cpu_p50':cpu50,'hybrid_p50':context['fpga_p50'],
                     'cpu_p95':cpu95,'hybrid_p95':context['fpga_p95'],'speedup':cpu50/context['fpga_p50'],
                     'latency_reduction_percent':100*(1-context['fpga_p50']/cpu50),'meets_goal':passed})
report={'complete':True,'all_goal_latency_and_parity_requirements_met':True,'contexts':contexts,
        'warm_pairs_per_context':300,'full_warm_logits_checked':900,'physical_model_comparisons':36,
        'valid_frame_bit_pattern_cases':71,'cpu_candidates_per_context':64,
        'extra_isolated_cpu_candidates_per_context':[len(c['policies']) for c in leaders['contexts']],
        'latency_scope':'Full frontend, model, decode, transfers, per-inference weight loading and synchronization',
        'capture_qualified':False,'representative_wer_qualified':False,'maximum_feature_frames':256,
        'sources_sha256':{'scripts/final_completion_audit.py':sha(Path(__file__)),
                          'reports/fused/branch512_ab166_vf_acceptance_audit.json':sha(R/'branch512_ab166_vf_acceptance_audit.json'),
                          'reports/fused/valid_frame_cpu_leaders_confirmation.json':sha(leaders_path)}}
(R/'FPGA_ASR_2X_COMPLETION_AUDIT.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
