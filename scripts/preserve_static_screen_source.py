"""Recover the earlier strict-parity diagnostic version and verify its hash."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'software/latency/short_static_benchmark.py').read_text(encoding='utf-8')
replacements=[
('    ap.add_argument(\'--trim-padding\', action=\'store_true\', help=\'Remove zero frames after the actual valid length\')\n',''),
('        baseline_x,n = frontend(audio)\n        x = np.ascontiguousarray(baseline_x[:,:,:int(n[0])]) if a.trim_padding else baseline_x\n        frames = x.shape[-1]\n','        x,n = frontend(audio); frames = x.shape[-1]\n'),
('if a.freeze_length or a.trim_padding else','if a.freeze_length else'),
('            outputs = {name:r.run(None,{\'features\':baseline_x if name.startswith(\'dynamic_\') else x,\n                                      \'feature_lengths\':feed[\'feature_lengths\']}) for name,r in runners.items()}\n            bit_parity = True; max_diff = 0.\n','            outputs = {name:r.run(None,feed) for name,r in runners.items()}\n'),
('''                np.testing.assert_array_equal(outputs[old][1],outputs[new][1])
                encoded = int(outputs[new][1][0])
                left,right = outputs[old][0][:,:encoded],outputs[new][0][:,:encoded]
                bit_parity &= np.array_equal(left,right)
                max_diff = max(max_diff,float(np.max(np.abs(left-right))))
                np.testing.assert_allclose(left,right,rtol=1e-5,atol=1e-4)
                assert decode(left[0],encoded,vocab) == decode(right[0],encoded,vocab)
''','                for left,right in zip(outputs[old],outputs[new]): np.testing.assert_array_equal(left,right)\n'),
('''            checks.append({'valid_length':valid,'original_optimized_valid_logits_bit_exact':bool(bit_parity),
                           'max_valid_logit_difference':max_diff,'within_tolerance':True,
                           'text_exact':True,'length_exact':True,'physical_oracle_bit_parity':True})
''',"            checks.append({'valid_length':valid,'cpu_bit_exact':True,'fpga_bit_exact':True,'physical_oracle_bit_parity':True})\n"),
('''            if a.trim_padding and not name.startswith('dynamic_'):
                features = np.ascontiguousarray(features[:,:,:int(lengths[0])])
            assert features.shape == (1,80,baseline_x.shape[-1] if name.startswith('dynamic_') else frames)
''','            assert features.shape == (1,80,frames)\n'),
("                   'runs':a.runs,'nodes':a.nodes,'freeze_length':a.freeze_length,'trim_padding':a.trim_padding,\n                   'cpu_threads':4,'main_core':3,'worker_cores':[0,1,2],\n", "                   'runs':a.runs,'nodes':a.nodes,'freeze_length':a.freeze_length,'cpu_threads':4,'main_core':3,'worker_cores':[0,1,2],\n")]
for old,new in replacements:
    assert old in source, old
    source=source.replace(old,new)
expected=json.loads((ROOT/'reports/fused/short_static_frames_screen50.json').read_text())['source_sha256']
payload=source.encode('utf-8')
assert hashlib.sha256(payload).hexdigest()==expected
out=ROOT/'software/latency/accepted_sources/short_static_frames_screen50.py'
out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(payload)
print('PASS preserved diagnostic source',expected)
