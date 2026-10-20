set root [file normalize [file join [file dirname [info script]] ..]]
create_project depthwise_channel_sim $root/build/depthwise_channel_sim -part xck26-sfvc784-2LV-c -force
add_files [list $root/rtl/experimental/fused_depthwise_channel.sv $root/rtl/experimental/fused_affine_quant.v]
add_files -fileset sim_1 $root/sim/tb_fused_depthwise_channel.sv
set_property top tb_fused_depthwise_channel [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation
run all
close_sim
set stream [open $root/build/depthwise_channel_sim/depthwise_channel_sim.sim/sim_1/behav/xsim/simulate.log r]
set log [read $stream];close $stream
if {![regexp {PASS: [0-9]+ depthwise channel arithmetic} $log]} {error "Depthwise simulation failed"}
close_project
