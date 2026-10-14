"""Prepare the combined residual/two-channel candidate and gated fast regression.

Only the simulation copy substitutes the MAC model. Hardware sources and
synthesis continue to instantiate real DSP48E2 primitives.
"""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
maclog=ROOT/'build/mac_conformance/mac_conformance.sim/sim_1/behav/xsim/simulate.log'
dwlog=ROOT/'build/bimodal_dw_sim/bimodal_dw_sim.sim/sim_1/behav/xsim/simulate.log'
assert 'PASS: 6000 vendor DSP48E2 MAC conformance cycles' in maclog.read_text()
assert 'PASS: 180 bimodal DW float32 cases' in dwlog.read_text()
assert not any(re.search(r'Fatal:|ERROR:',p.read_text()) for p in (maclog,dwlog))
def write(name,text):
    p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():assert p.read_text()==text,str(p)
    else:p.write_bytes(text.encode())
text=(ROOT/'rtl/experimental/qn_branch_inner.sv').read_text().replace('qn_branch_inner','qn_branch_bimodal_inner')
text=text.replace('fused_depthwise_quad','fused_depthwise_bimodal').replace('short_mode=times<=16;','short_mode=times<=32;')
text=text.replace("channel_step=short_mode?10'd4:10'd1;", "channel_step=times<=16?10'd4:times<=32?10'd2:10'd1;")
text=text.replace('fetch_channel==3)','fetch_channel==channel_step-1)')
write('rtl/experimental/qn_branch_bimodal_inner.sv',text)
text=(ROOT/'rtl/experimental/qn_branch_axis.sv').read_text().replace('qn_branch_inner','qn_branch_bimodal_inner')
write('rtl/experimental/qn_branch_bimodal_axis.sv',text)
text=(ROOT/'scripts/create_branch_tb.py').read_text()
text=text.replace('verification/branch-vectors','verification/bimodal-branch-vectors')
text=text.replace('(65,63,5,29))','(65,63,5,29),(31,30,3,41),(32,31,3,11),(33,33,3,39))')
text=text.replace('tb_qn_branch_axis','tb_qn_branch_bimodal_axis').replace('scripts/branch_sim.tcl','scripts/branch_bimodal_sim.tcl')
text=text.replace('branch_rtl_fixtures.json','branch_bimodal_rtl_fixtures.json')
write('scripts/create_branch_bimodal_tb.py',text)
exec(compile(text,str(ROOT/'scripts/create_branch_bimodal_tb.py'),'exec'),{'__file__':str(ROOT/'scripts/create_branch_bimodal_tb.py')})
p=ROOT/'sim/tb_qn_branch_bimodal_axis.sv';tb=p.read_text()
base=(ROOT/'sim/tb_qn_quad_compact_axis.sv').read_text()
legacy=base[base.index('  stream_case(1,1,1,1);'):base.index('  $display("PASS:')]
start=tb.index('  stream_case(7,7,5,29);');end=tb.index('  $display("PASS:',start)
extras=tb[start:end].replace('  stream_case(7,7,5,29);\n','')
extras=extras.replace('  inject_bad=1;residual_case',
                     '  residual_case(31,30,3,41);\n  residual_case(32,31,3,11);\n  residual_case(33,33,3,39);\n  inject_bad=1;residual_case')
tb=tb[:start]+legacy+extras+tb[end:];p.write_text(tb)
hardware=ROOT/'rtl/experimental/qn_branch_pw_core.v';source=hardware.read_text()
assert source.count('DSP48E2 #(')==1
quad=(ROOT/'rtl/experimental/qn_quad_pw_core.v').read_text()
def mac_instance(s):return s[s.index('   DSP48E2 #('):s.index('  end\n end endgenerate',s.index('   DSP48E2 #('))]
assert mac_instance(source)==mac_instance(quad),'Vendor conformance pins must match hardware'
fast=source.replace('DSP48E2 #(','qn_mac_model #(')
write('sim/fast/qn_branch_pw_core.v',fast)
tcl='''set root [file normalize [file join [file dirname [info script]] ..]]
create_project branch_bimodal_fast_sim $root/build/branch_bimodal_fast_sim -part xck26-sfvc784-2LV-c -force
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
foreach source {qn_branch_bimodal_axis.sv qn_branch_bimodal_inner.sv fused_depthwise_bimodal.sv fused_affine_quant_compact.sv fused_affine_quant_select_wrap.sv} {
 add_files $root/rtl/experimental/$source
}
add_files $root/sim/fast/qn_branch_pw_core.v
add_files $root/sim/qn_mac_model.sv
add_files -fileset sim_1 $root/sim/tb_qn_branch_bimodal_axis.sv
set_property top tb_qn_branch_bimodal_axis [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
launch_simulation
run all
close_sim
set f [open $root/build/branch_bimodal_fast_sim/branch_bimodal_fast_sim.sim/sim_1/behav/xsim/simulate.log r]
set result [read $f];close $f
if {![string match {*PASS: 25 two-output residual branches*} $result]} {error "Combined branch regression failed"}
close_project
'''
write('scripts/branch_bimodal_fast_sim.tcl',tcl)
vendor=tcl.replace('branch_bimodal_fast_sim','branch_bimodal_vendor_sim')
vendor=vendor.replace('add_files $root/sim/fast/qn_branch_pw_core.v\nadd_files $root/sim/qn_mac_model.sv',
                      'add_files $root/rtl/experimental/qn_branch_pw_core.v')
write('scripts/branch_bimodal_vendor_sim.tcl',vendor)
(ROOT/'scripts/branch_bimodal_sim.tcl').write_text('source [file join [file dirname [info script]] branch_bimodal_vendor_sim.tcl]\n')
manifest_path=ROOT/'reports/fused/branch_bimodal_rtl_fixtures.json'
manifest=json.loads(manifest_path.read_text());manifest['total_cases']=25
manifest['sources_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in manifest['sources_sha256']}
manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
paths=[maclog,dwlog,hardware,ROOT/'sim/fast/qn_branch_pw_core.v',ROOT/'sim/qn_mac_model.sv',
       ROOT/'sim/tb_mac_conformance.sv',ROOT/'scripts/create_mac_conformance.py',ROOT/'scripts/create_branch_bimodal_build.py']
paths += list((ROOT/'verification/bimodal-dw').glob('*'))
paths += [ROOT/'rtl/experimental/fused_depthwise_bimodal.sv',ROOT/'sim/tb_bimodal_dw.sv',
          ROOT/'scripts/create_bimodal_dw.py',ROOT/'scripts/create_bimodal_dw_tb.py',ROOT/'scripts/bimodal_dw_sim.tcl']
proof={'complete':True,'hardware_execution':False,'full_block_simulation_passed':False,
    'mac_model_vendor_conformance_cycles':6000,'depthwise_unit_cases':180,
    'simulation_substitution':'Only DSP48E2 is replaced in a derived simulation-only source; all controller/memory/quantizer RTL retained',
    'sources_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
(ROOT/'reports/fused/branch_bimodal_unit_evidence.json').write_text(json.dumps(proof,indent=2)+'\n')
print('Prepared combined candidate, 25 full-block cases and source-bound vendor MAC conformance')
