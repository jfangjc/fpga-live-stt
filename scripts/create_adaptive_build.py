"""Create isolated adaptive unit/full-block builds without changing stream work."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
unitlog=ROOT/'build/adaptive_dw_sim/adaptive_dw_sim.sim/sim_1/behav/xsim/simulate.log'
assert 'PASS: 135 adaptive DW float32 cases' in unitlog.read_text()
assert not re.search(r'Fatal:|ERROR:',unitlog.read_text())
files=[ROOT/n for n in ('rtl/experimental/fused_depthwise_adaptive.sv','rtl/experimental/fused_affine_quant_exact.sv',
                        'sim/tb_adaptive_dw.sv','scripts/create_adaptive_dw_tb.py')]
files+=list((ROOT/'verification/adaptive-dw').glob('*'))+[unitlog]
proof={'complete':True,'hardware_execution':False,'cases':135,'beats':210,
       'sources_and_evidence_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
(ROOT/'reports/fused/adaptive_unit_validation.json').write_text(json.dumps(proof,indent=2)+'\n')
text=(ROOT/'scripts/create_stream_tb.py').read_text()
text=text.replace('verification/stream-vectors','verification/adaptive-vectors')
text=text.replace("(17,17,8,1))","(17,17,8,1),(7,7,5,29),(16,9,3,39),(13,0,8,1))")
text=text.replace('module tb_qn_stream_axis;','module tb_qn_adaptive_axis;')
text=text.replace("ROOT/'sim/tb_qn_stream_axis.sv'","ROOT/'sim/tb_qn_adaptive_axis.sv'")
text=text.replace('  stream_case(17,17,8,1);','  stream_case(17,17,8,1);\n  stream_case(7,7,5,29);\n  stream_case(16,9,3,39);\n  stream_case(13,0,8,1);')
# Consecutive weight beats exercise real DMA throughput while respecting
# stable setup at the falling edge and output backpressure.
text=text.replace("text=text.replace('VECTOR_ROOT',dest.as_posix())",
                  "text=text.replace('begin @(negedge clk);data=value;', 'begin if(clk!==0)@(negedge clk);data=value;')\ntext=text.replace('VECTOR_ROOT',dest.as_posix())")
(ROOT/'scripts/create_adaptive_tb.py').write_bytes(text.encode())
text=(ROOT/'scripts/stream_sim.tcl').read_text().replace('stream_sim','adaptive_sim').replace('tb_qn_stream_axis','tb_qn_adaptive_axis')
text=text.replace('qn_stream_axis.sv qn_stream_inner.sv qn_stream_pw_core.v fused_depthwise_stream.sv',
                  'qn_adaptive_axis.sv qn_adaptive_inner.sv qn_stream_pw_core.v fused_depthwise_adaptive.sv')
text=text.replace('PASS: 11','PASS: 14')
(ROOT/'scripts/adaptive_sim.tcl').write_bytes(text.encode())
text=(ROOT/'scripts/stream_synth.tcl').read_text().replace('stream_system','adaptive_system').replace('Prototype_v3_stream','Prototype_v3_adaptive')
text=text.replace('$root/build/adaptive_system','$root/build/adaptive_system_v2')
text=text.replace('open_project $root/Prototype_v2.xpr','open_project $root/build/stream_system/Prototype_v3_stream.xpr')
text=text.replace('set old [get_files -quiet */qn_cached_axis.v]',
                  'foreach source {qn_stream_axis.sv qn_stream_inner.sv fused_depthwise_stream.sv} {\n set files [get_files -quiet */$source]\n if {[llength $files]} {remove_files $files}\n}\nset old [get_files -quiet */qn_cached_axis.v]')
text=text.replace('qn_stream_axis.sv qn_stream_inner.sv qn_stream_pw_core.v fused_depthwise_stream.sv',
                  'qn_adaptive_axis.sv qn_adaptive_inner.sv qn_stream_pw_core.v fused_depthwise_adaptive.sv')
text=text.replace('check_stream_software.py','check_adaptive_software.py').replace('stream_synth_utilization','adaptive_synth_utilization')
(ROOT/'scripts/adaptive_synth.tcl').write_bytes(text.encode())
text=(ROOT/'scripts/stream_implement.tcl').read_text().replace('stream_system','adaptive_system').replace('Prototype_v3_stream','Prototype_v3_adaptive')
text=text.replace('$root/build/adaptive_system/','$root/build/adaptive_system_v2/')
text=text.replace('asr-v3-stream','asr-v3-adaptive').replace('asr_v3_stream.xsa','asr_v3_adaptive.xsa')
(ROOT/'scripts/adaptive_implement.tcl').write_bytes(text.encode())
print('Prepared isolated adaptive full-block regression and implementation scripts')
