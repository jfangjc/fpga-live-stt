# Isolated primitive simulation, preserving the production Vivado project.
set root [file normalize [file join [file dirname [info script]] ..]]
create_project fused_requant_sim $root/build/fused_requant_sim -part xck26-sfvc784-2LV-c -force
add_files $root/rtl/experimental/fused_requant.v
add_files -fileset sim_1 $root/sim/tb_fused_requant.sv
set_property top tb_fused_requant [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
set simdir $root/build/fused_requant_sim/fused_requant_sim.sim/sim_1/behav/xsim
file mkdir $simdir
file copy -force $root/sim/fused_vectors/input.mem $simdir/input.mem
file copy -force $root/sim/fused_vectors/expected.mem $simdir/expected.mem
launch_simulation
run all
close_sim
set stream [open $simdir/simulate.log r]
set log [read $stream]
close $stream
if {![regexp {PASS: 1024 four-lane requant vectors} $log]} {
    error "Requant primitive simulation did not pass"
}
close_project
