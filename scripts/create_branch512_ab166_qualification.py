"""Carry all physical parity and strongest-CPU latency gates to the retimed MAC."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
cpu=(ROOT/'software/latency/tune_maskfast_cpu.py').read_text()
a=cpu.index("policies=[{'graph':g,");b=cpu.index('frontend=Frontend(',a)
cpu=cpu[:a]+"""policies=[{'graph':g,'threads':t,'spin':spin,'level':level,'tail_impl':impl}
          for g in ('tail','pool') for t in (1,2,3,4) for spin in (0,10)
          for level in ('extended','all') for impl in ('original','maskfast')]
assert len(policies)==64
"""+cpu[b:]
cpu=cpu.replace("elapsed,_,actual_length,actual_text=call(index);assert actual_text==text", "elapsed,actual_logits,actual_length,actual_text=call(index);np.testing.assert_array_equal(actual_logits,reference);assert actual_text==text")
cpu=cpu.replace("'source_sha256':sha(__file__)", "'candidate_count':64,'runs_per_context_policy':a.runs,'all_warm_logits_bit_exact':True,'source_sha256':sha(__file__)")
cpu_dest=ROOT/'software/latency/tune_branch512_ab166_cpu.py'
if cpu_dest.exists():assert cpu_dest.read_text()==cpu
else:cpu_dest.write_text(cpu,newline='\n')
paths=[p for p in (ROOT/'scripts').glob('*branch512_guard166*') if p.name.startswith(('prepare_','finalize_','install_','run_','qualify_'))]
paths+=list((ROOT/'software/latency').glob('*branch512_guard166*.py'))
paths+=list((ROOT/'software/latency').glob('test_guard_*.py'))
for path in paths:
    text=path.read_text().replace('branch512_guard166','branch512_ab166').replace('branch512-guard166','branch512-ab166')
    text=text.replace('check_branch512_guard_software.py','check_branch512_ab_software.py').replace('branch512_guard_regression_evidence.json','branch512_ab_regression_evidence.json')
    text=text.replace('test_guard_','test_ab_').replace('FPGA-ASR-header-guard-','FPGA-ASR-DSP-input-register-')
    if path.name.startswith('prepare_'):
        old="paths += [drop_parent]+[ROOT/path for path in drop_record['sources_sha256']]"
        extra="""
guard_parent=ROOT/'reports/fused/branch512_guard_regression_evidence.json'
guard_record=json.loads(guard_parent.read_text());assert guard_record['complete']
for path,value in guard_record['sources_sha256'].items():assert sha(ROOT/path)==value,path
paths += [guard_parent]+[ROOT/path for path in guard_record['sources_sha256']]
"""
        assert old in text;text=text.replace(old,old+extra)
    if path.name=='qualify_branch512_guard166_maskfast.py':
        a=text.index("download('reports/fused/branch512_maskfast_cpu_policy_clean.json')")
        b=text.index("download('reports/fused/branch512_more_pool_oracle.json')",a)
        text=text[:a]+(ROOT/'scripts/ab_cpu_policy_refresh_fragment.txt').read_text()+text[b:]
    if path.name=='tune_branch512_guard166_maskfast_policy.py':
        text=text.replace('branch512_maskfast_cpu_policy_clean.json','branch512_ab166_cpu_policy_wide.json')
        text=text.replace("assert cpu_screen['complete'] and cpu_screen['all_logits_bit_exact']", "assert cpu_screen['complete'] and cpu_screen['all_logits_bit_exact'] and cpu_screen['all_warm_logits_bit_exact']\nassert cpu_screen['candidate_count']==64")
    name=path.relative_to(ROOT).as_posix().replace('branch512_guard166','branch512_ab166').replace('test_guard_','test_ab_')
    dest=ROOT/name
    if dest.exists():assert dest.read_text()==text,dest
    else:dest.write_text(text,newline='\n')
stage=(ROOT/'scripts/verify_branch512_guard166_stage.py').read_text().replace('branch512_guard166','branch512_ab166').replace('test_guard_','test_ab_')
dest=ROOT/'scripts/verify_branch512_ab166_stage.py'
if dest.exists():assert dest.read_text()==stage
else:dest.write_text(stage,newline='\n')
print('Prepared isolated retimed-MAC firmware and sequential physical parity/latency tools')
