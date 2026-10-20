set root [file normalize [file join [file dirname [info script]] ..]]
create_project fused_pair_sim $root/build/fused_pair_sim -part xck26-sfvc784-2LV-c -force
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
add_files [list $root/rtl/experimental/qn_fused_axis.sv $root/rtl/experimental/qn_fused_core.v $root/rtl/experimental/fused_depthwise_channel.sv $root/rtl/experimental/fused_affine_quant.v]
add_files -fileset sim_1 $root/sim/tb_qn_fused_axis.sv
set_property top tb_qn_fused_axis [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation
run all
close_sim
set stream [open $root/build/fused_pair_sim/fused_pair_sim.sim/sim_1/behav/xsim/simulate.log r]
set log [read $stream];close $stream
if {![regexp {PASS: [0-9]+ fused depthwise/pointwise arithmetic} $log]} {error "Fused pair simulation failed"}
close_project
