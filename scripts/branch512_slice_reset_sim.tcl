set root [file normalize [file join [file dirname [info script]] ..]]
create_project branch512_slice_reset_sim $root/build/branch512_slice_reset_sim -part xck26-sfvc784-2LV-c -force
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
foreach source {qn_branch512_slice_axis.sv qn_branch512_slice_inner.sv fused_depthwise_bimodal.sv fused_affine_quant_compact.sv fused_affine_quant_select_wrap.sv} {
 add_files $root/rtl/experimental/$source
}
add_files $root/sim/fast/qn_branch512_slice_pw_core.v
add_files $root/sim/qn_mac_model.sv
add_files -fileset sim_1 $root/sim/tb_qn_branch512_slice_reset.sv
set_property top tb_qn_branch512_slice_reset [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
launch_simulation
run all
close_sim
set f [open $root/build/branch512_slice_reset_sim/branch512_slice_reset_sim.sim/sim_1/behav/xsim/simulate.log r]
set result [read $f];close $f
if {![string match {*PASS: 4 full-pipeline reset/replay cases*} $result]} {error "Combined branch regression failed"}
close_project
