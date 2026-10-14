set root [file normalize [file join [file dirname [info script]] ..]]
create_project depthwise_model_sim $root/build/depthwise_model_sim -part xck26-sfvc784-2LV-c -force
add_files [list $root/rtl/experimental/fused_depthwise_channel.sv $root/rtl/experimental/fused_affine_quant.v]
add_files -fileset sim_1 $root/sim/tb_depthwise_model.sv
set_property top tb_depthwise_model [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation
run all
close_sim
set stream [open $root/build/depthwise_model_sim/depthwise_model_sim.sim/sim_1/behav/xsim/simulate.log r]
set log [read $stream];close $stream
if {![regexp {PASS: 256 real checkpoint depthwise channels} $log]} {error "Depthwise model replay failed"}
close_project
