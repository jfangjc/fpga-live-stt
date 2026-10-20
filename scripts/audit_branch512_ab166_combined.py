"""Audit source-bound full-path measurements; report goal status without relaxing it."""
import hashlib
import json
import argparse
import ast
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT/'reports/fused'
parser = argparse.ArgumentParser()
parser.add_argument('--variant', choices=('maskfast', 'neon_maskfast', 'irq', 'dma128', 'vf'), default='neon_maskfast')
parser.add_argument('--report', type=Path)
parser.add_argument('--out', type=Path)
args = parser.parse_args()
HW_LABEL = 'branch512_dma128166' if args.variant == 'dma128' else 'branch512_ab166'
LABEL = HW_LABEL+'_irq' if args.variant == 'dma128' else HW_LABEL+'_'+args.variant
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
read = lambda name: json.loads((REPORTS/name).read_text())
cpu_screen_name = 'valid_frame_cpu_policy.json' if args.variant == 'vf' else 'branch512_ab166_cpu_policy_wide.json'
cpu_screen_source = 'tune_valid_frame_cpu.py' if args.variant == 'vf' else 'tune_branch512_ab166_cpu.py'
cpu = read(cpu_screen_name)
policy_path = REPORTS/f'{LABEL}_latency_policy.json'
policy = json.loads(policy_path.read_text())
result_path = (args.report or REPORTS/f'{LABEL}_latency_confirmation.json').resolve()
result = json.loads(result_path.read_text())
physical_label = (HW_LABEL if args.variant == 'dma128' else
                  'branch512_ab166_neon_maskfast' if args.variant == 'irq' else LABEL)
physical = read(f'{physical_label}_physical_validation.json')
firmware = read(f'{HW_LABEL}_firmware_evidence.json')
maskfast = read('residual_tail_maskfast_validation.json')
fpga_library = 'software/ort_fpga_stream_branch512/libort_fpga.so'
if args.variant in ('neon_maskfast', 'irq', 'dma128', 'vf'):
    neon = read('branch512_neon_evidence.json')
    assert neon['complete'] and neon['arithmetic_and_program_construction_unchanged']
    assert neon['guarded_byte_cases'] == 1024 and neon['packet_checks'] == 288
    for name, value in neon['sources_sha256'].items():
        assert sha(ROOT/name) == value, name
    assert result['neon_evidence_sha256'] == sha(REPORTS/'branch512_neon_evidence.json')
    assert result['library_sha256'] == neon['library_sha256'] and result['vector_output_unpacking']
    fpga_library = 'software/ort_fpga_stream_branch512_neon/libort_fpga.so'
else:
    assert result['library_sha256'] == firmware['sources_and_evidence_sha256'][fpga_library]
assert maskfast['complete'] and maskfast['all_bit_exact']
assert len(maskfast['micro_cases']) == 567 and len(maskfast['full_model_cases']) == 36
assert result['maskfast_validation_sha256'] == sha(REPORTS/'residual_tail_maskfast_validation.json')
assert result['residual_tail_library_sha256'] == maskfast['library_sha256']
assert maskfast['implementation_sha256'] == sha(ROOT/'software/latency/residual_tail_maskfast.cc')
assert cpu['complete'] and cpu['candidate_count'] == 64
assert cpu['all_warm_logits_bit_exact'] and not cpu['hardware_execution']
assert cpu['source_sha256'] == sha(ROOT/'software/latency'/cpu_screen_source)
for context in cpu['contexts']:
    candidates = context['candidates']
    assert len(candidates) == 64
    assert len({json.dumps(c['policy'], sort_keys=True) for c in candidates}) == 64
    rows = [r for r in cpu['runs'] if r['context_seconds'] == context['context_seconds']]
    assert len(rows) == cpu['runs_per_context_policy']
    for candidate in candidates:
        values = [r['seconds'][str(candidate['index'])] for r in rows]
        assert np.isclose(candidate['p50'], np.median(values), rtol=0, atol=1e-12)
    assert context['selected'] == min(candidates, key=lambda c: c['p50'])
assert policy['cpu_policy_screen_sha256'] == sha(REPORTS/cpu_screen_name)
assert result['policy_screen_sha256'] == sha(policy_path)
assert result['source_sha256'] == sha(ROOT/'software/latency'/f'confirm_{LABEL}_latency.py')
assert policy['source_sha256'] == sha(ROOT/'software/latency'/f'tune_{LABEL}_policy.py')
assert physical['source_sha256'] == sha(ROOT/'software/latency'/f'validate_{physical_label}_physical.py')
assert physical['graph_sha256'] == sha(REPORTS/f'{physical_label}_physical_validation.onnx')
assert result['timer_source_sha256'] == sha(ROOT/'software/latency'/f'{LABEL}_benchmark.py')
assert firmware['complete'] and firmware['setup_slack_ns'] >= .001 and firmware['hold_slack_ns'] >= 0
assert len(physical['clips']) == 36 and all(c['physical_oracle_bit_exact'] for c in physical['clips'])
assert result['complete'] and result['hardware_execution']
assert result['runs_per_context'] == 300 and result['weight_transfers_inside_timing']
assert result['maximum_feature_frames'] == 256
isolated = None
original_isolated = None
if args.variant in ('irq', 'dma128', 'vf'):
    helper = ROOT/f'software/latency/{HW_LABEL}_irq_benchmark.py'
    assert result['irq_placement_source_sha256'] == sha(helper)
    tree = ast.parse(helper.read_text())
    # This wrapper only adds IRQ configuration and evidence binding; model
    # construction and execution use the physically qualified parent.
    assert {n.name for n in tree.body if isinstance(n, ast.FunctionDef)} == {'configure', 'bindings'}
    assert all(isinstance(n, (ast.Expr, ast.ImportFrom, ast.FunctionDef)) for n in tree.body)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom): assert node.module == HW_LABEL+'_neon_maskfast_benchmark'
    isolated_name = 'valid_frame_cpu_isolated_confirmation.json' if args.variant == 'vf' else 'branch512_ab166_cpu_isolated_confirmation.json'
    isolated_source = 'confirm_valid_frame_cpu_isolated.py' if args.variant == 'vf' else 'confirm_branch512_ab166_cpu_isolated.py'
    isolated_path = REPORTS/isolated_name
    assert result['isolated_cpu_confirmation_sha256'] == sha(isolated_path)
    isolated = json.loads(isolated_path.read_text())
    assert isolated['complete'] and not isolated['hardware_execution'] and not isolated['fpga_session_loaded']
    assert isolated['cpu_policy_screen_sha256'] == sha(REPORTS/cpu_screen_name)
    assert isolated['cpu_model_sha256'] == result['cpu_model_sha256']
    assert isolated['source_sha256'] == sha(ROOT/'software/latency'/isolated_source)
    for context in isolated['contexts']:
        assert context['all_warm_logits_bit_exact'] and len(context['seconds']) == isolated['runs_per_context'] >= 100
        assert np.isclose(context['cpu_p50'], np.median(context['seconds']), rtol=0, atol=1e-12)
        assert np.isclose(context['cpu_p95'], np.percentile(context['seconds'], 95), rtol=0, atol=1e-12)
if args.variant == 'vf':
    validation_path = REPORTS/'valid_frame_frontend_validation.json'
    validation = json.loads(validation_path.read_text())
    assert validation['complete'] and validation['all_model_inputs_bit_exact'] and len(validation['cases']) == 71
    assert validation['source_sha256'] == sha(ROOT/'software/latency/validate_valid_frame_frontend.py')
    assert validation['candidate_sha256'] == sha(ROOT/'software/latency/frontend_valid_frames.py')
    assert validation['pinned_frontend_sha256'] == sha(ROOT/'software/model-tools/citrinet_cpu.py')
    for report in (cpu, isolated, policy, physical, result):
        assert report['valid_frame_frontend_sha256'] == validation['candidate_sha256']
        assert report['valid_frame_validation_sha256'] == sha(validation_path)
    original_tree = ast.parse((ROOT/'software/model-tools/citrinet_cpu.py').read_text())
    original_class = next(n for n in original_tree.body if isinstance(n, ast.ClassDef) and n.name == 'Frontend')
    original_method = next(n for n in original_class.body if isinstance(n, ast.FunctionDef) and n.name == '__call__')
    padding = [n for n in original_method.body if isinstance(n, ast.Assign) and
               isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute) and
               isinstance(n.value.func.value, ast.Name) and n.value.func.value.id == 'np' and n.value.func.attr == 'pad']
    assert len(padding) == 1
    original_method.body.remove(padding[0])
    candidate_tree = ast.parse((ROOT/'software/latency/frontend_valid_frames.py').read_text())
    candidate_class = next(n for n in candidate_tree.body if isinstance(n, ast.ClassDef))
    candidate_method = next(n for n in candidate_class.body if isinstance(n, ast.FunctionDef))
    assert ast.dump(original_method, include_attributes=False) == ast.dump(candidate_method, include_attributes=False)
    original_path = REPORTS/'branch512_ab166_cpu_isolated_confirmation.json'
    assert result['original_isolated_cpu_confirmation_sha256'] == sha(original_path)
    original_isolated = json.loads(original_path.read_text())
    assert original_isolated['complete'] and not original_isolated['fpga_session_loaded']
    assert original_isolated['cpu_model_sha256'] == result['cpu_model_sha256']
    assert original_isolated['source_sha256'] == sha(ROOT/'software/latency/confirm_branch512_ab166_cpu_isolated.py')
    assert original_isolated['cpu_policy_screen_sha256'] == sha(REPORTS/'branch512_ab166_cpu_policy_wide.json')
    for context in original_isolated['contexts']:
        assert context['all_warm_logits_bit_exact'] and len(context['seconds']) == original_isolated['runs_per_context'] >= 100
        assert np.isclose(context['cpu_p50'], np.median(context['seconds']), rtol=0, atol=1e-12)
        assert np.isclose(context['cpu_p95'], np.percentile(context['seconds'], 95), rtol=0, atol=1e-12)
for key, path in [('library_sha256', fpga_library),
                  ('boundary_library_sha256', 'software/latency/libboundary_lut.so'),
                  ('cpu_model_sha256', 'research/fused/cpu-int8-cse.onnx'),
                  ('residual_tail_library_sha256', 'software/latency/libresidual_tail_maskfast.so')]:
    assert result[key] == policy[key] == physical[key] == sha(ROOT/path), key
assert result['firmware_sha256'] == firmware['firmware_bin_sha256']
app = 'asr-v3-branch512-dma128166' if args.variant == 'dma128' else 'asr-v3-branch512-ab166'
assert result['firmware_sha256'] == sha(ROOT/f'deployment/{app}/{app}.bit.bin')
if args.variant == 'dma128':
    assert firmware['dma_max_burst_beats'] == 128
    assert set(firmware['dma_config_changes']) == {'c_mm2s_burst_size', 'c_s2mm_burst_size'}
    blocks = read('branch512_dma128166_physical_blocks.json')
    assert blocks['complete'] and blocks['hardware_execution'] and blocks['all_outputs_bit_exact']
    assert len(blocks['cases']) == 294
    assert blocks['firmware_sha256'] == result['firmware_sha256']
    for name, expected in firmware['sources_and_evidence_sha256'].items():
        assert sha(ROOT/name) == expected, name
contexts = []
assert [c['context_seconds'] for c in result['contexts']] == [.5, 1, 2.5]
for context in result['contexts']:
    seconds = context['context_seconds']
    selected_cpu = next(c for c in cpu['contexts'] if c['context_seconds'] == seconds)['selected']['policy']
    assert context['cpu_policy'] == selected_cpu == policy['cpu_policies'][str(seconds)]
    assert context['physical_oracle_bit_exact'] and context['all_warm_logits_bit_exact']
    assert context['warm_logit_checks'] == 300 and len(context['runs']) == 300
    for row in context['runs']:
        assert row['all_logits_bit_exact'] and set(row['order']) == {'cpu', 'fpga'}
        fp = row['results']['fpga']; cp = row['results']['cpu']
        assert fp['counters']['loads'] == 256 and fp['counters']['ioctls'] == 24
        assert fp['counters']['physical_calls'] == 128 and fp['counters']['oracle_calls'] == 0
        assert cp['counters']['physical_calls'] == cp['counters']['oracle_calls'] == 0
        assert fp['feature_frames'] == cp['feature_frames'] == int(seconds*100)+1
        assert fp['counters']['tx_bytes'] > 10_000_000
        assert fp['text'] == cp['text'] and fp['length'] == cp['length']
    for kind in ('cpu', 'fpga'):
        values = [row['results'][kind]['seconds'] for row in context['runs']]
        assert np.isclose(context[kind+'_p50'], np.median(values), rtol=0, atol=1e-12)
        assert np.isclose(context[kind+'_p95'], np.percentile(values, 95), rtol=0, atol=1e-12)
    baseline_p50, baseline_p95 = context['cpu_p50'], context['cpu_p95']
    if isolated is not None:
        alone = next(c for c in isolated['contexts'] if c['context_seconds'] == seconds)
        assert alone['cpu_policy'] == selected_cpu
        baseline_p50 = min(baseline_p50, alone['cpu_p50'])
        baseline_p95 = min(baseline_p95, alone['cpu_p95'])
        if original_isolated is not None:
            original = next(c for c in original_isolated['contexts'] if c['context_seconds'] == seconds)
            baseline_p50 = min(baseline_p50, original['cpu_p50'])
            baseline_p95 = min(baseline_p95, original['cpu_p95'])
        assert context['strongest_cpu_p50'] == baseline_p50 and context['strongest_cpu_p95'] == baseline_p95
        assert np.isclose(context['speedup_against_strongest_cpu'], baseline_p50/context['fpga_p50'], rtol=0, atol=1e-12)
    meets = context['fpga_p50'] <= .5*baseline_p50 and context['fpga_p95'] < baseline_p95
    assert context['meets_50_percent'] == meets
    contexts.append({k: context[k] for k in ('context_seconds', 'cpu_p50', 'fpga_p50',
                                            'cpu_p95', 'fpga_p95', 'speedup_factor', 'meets_50_percent')})
    contexts[-1].update(strongest_cpu_p50=baseline_p50, strongest_cpu_p95=baseline_p95,
                        speedup_against_strongest_cpu=baseline_p50/context['fpga_p50'])
accepted = all(c['meets_50_percent'] for c in contexts)
assert result['twofold_speed_acceptance'] == accepted
audit = {'complete': True, 'evidence_valid': True, 'twofold_speed_acceptance': accepted,
         'confirmation_sha256': sha(result_path), 'cpu_screen_sha256': sha(REPORTS/cpu_screen_name),
         'contexts': contexts, 'source_sha256': sha(Path(__file__)),
         'scope': 'Tested warm full audio paths only; no live capture or representative WER qualification'}
output_path = args.out or (REPORTS/f'{LABEL}_acceptance_audit.json' if not args.report
                          else result_path.with_name(result_path.stem+'_acceptance_audit.json'))
output_path.write_text(json.dumps(audit, indent=2)+'\n')
print(json.dumps(audit))
