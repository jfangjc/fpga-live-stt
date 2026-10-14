# Standalone cached engine simulation; no deployed project is opened or changed.
set root [file normalize [file join [file dirname [info script]] ..]]
create_project cached_sim $root/build/cached_sim -part xck26-sfvc784-2LV-c -force
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
add_files $root/rtl/qn_cached_axis.v
add_files -fileset sim_1 $root/sim/tb_qn_cached_axis.sv
set_property top tb_qn_cached_axis [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation
run all
close_sim
set log_file [open $root/build/cached_sim/cached_sim.sim/sim_1/behav/xsim/simulate.log r]
set simulation_log [read $log_file]
close $log_file
if {![regexp {PASS: [0-9]+ cached arithmetic/protocol/reset cases} $simulation_log]} {
    error "Cached engine testbench did not reach PASS; inspect simulation log"
}
close_project
