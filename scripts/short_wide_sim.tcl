set root [file normalize [file join [file dirname [info script]] ..]]
create_project short_wide_sim $root/build/short_wide_sim -part xck26-sfvc784-2LV-c -force
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
add_files [list $root/rtl/experimental/qn_short_wide_axis.sv $root/rtl/experimental/qn_short_cache_core.v $root/rtl/experimental/fused_depthwise_channel_wide.sv $root/rtl/experimental/fused_affine_quant.v]
add_files -fileset sim_1 $root/sim/tb_qn_short_cache_axis.sv
set_property top tb_qn_short_cache_axis [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation
run all
close_sim
set stream [open $root/build/short_wide_sim/short_wide_sim.sim/sim_1/behav/xsim/simulate.log r]
set log [read $stream];close $stream
if {![regexp {PASS: [0-9]+ short-cache retained pair arithmetic} $log]} {error "Short-cache simulation failed"}
close_project
