"""Bind exact arithmetic checks and isolated synthesis, without a board claim."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];reports=ROOT/'reports/fused'
proof=json.loads((reports/'compact_requant_integer_validation.json').read_text())
assert proof['complete'] and proof['all_float32_bit_exact'] and proof['random_cases']==1000000
assert proof['targeted_half_cases']==100000 and proof['rtl_vectors']==2400
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(ROOT/'software/latency/compact_requant_reference.py')==proof['reference_sha256']
assert sha(ROOT/'verification/exact-requant/quant.mem')==proof['fixture_sha256']
log=ROOT/'build/compact_requant_sim/compact_requant_sim.sim/sim_1/behav/xsim/simulate.log'
assert 'PASS: 9600 float32-equivalent lanes' in log.read_text()
assert not re.search(r'Fatal:|ERROR:',log.read_text())
paths=[log,reports/'compact_requant_integer_validation.json',ROOT/'rtl/experimental/fused_affine_quant_compact.sv',
       ROOT/'software/latency/compact_requant_reference.py',ROOT/'verification/exact-requant/quant.mem',
       ROOT/'sim/tb_compact_requant.sv',ROOT/'scripts/test_compact_requant.py',ROOT/'scripts/compact_requant_sim.tcl',
       ROOT/'scripts/compact_requant_synth.tcl']
area={}
for variant in ('exact','compact'):
    path=reports/f'requant_{variant}_synth_utilization.rpt';text=path.read_text()
    area[variant]={name:int(re.search(r'\| '+label+r'\s*\|\s*(\d+)',text).group(1))
                   for name,label in (('luts',r'CLB LUTs\*'),('registers','CLB Registers'),('dsps','DSPs'))}
    paths += [path,reports/f'requant_{variant}_synth_timing.rpt']
result={'complete':True,'hardware_execution':False,'whole_model_speed_qualified':False,
        'random_cases':1000000,'targeted_half_cases':100000,'rtl_lanes':9600,
        'isolated_synthesis_lanes':32,'area':area,'lut_reduction_percent':100*(1-area['compact']['luts']/area['exact']['luts']),
        'sources_and_evidence_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}}
(reports/'compact_requant_evidence.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS: compact exact arithmetic, primitive RTL and isolated resource evidence bound')
