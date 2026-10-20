set root [file normalize [file join [file dirname [info script]] ..]]
create_project fused_se_sim $root/build/fused_se_sim -part xck26-sfvc784-2LV-c -force
add_files $root/rtl/experimental/fused_se_reduce.v
add_files -fileset sim_1 $root/sim/tb_fused_se_reduce.sv
set_property include_dirs $root/sim/se_vectors [get_filesets sim_1]
set_property top tb_fused_se_reduce [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
set simdir $root/build/fused_se_sim/fused_se_sim.sim/sim_1/behav/xsim
file mkdir $simdir
foreach name {input.mem expected.mem} {
    file copy -force $root/sim/se_vectors/$name $simdir/$name
}
launch_simulation
run all
close_sim
set stream [open $simdir/simulate.log r]
set log [read $stream]
close $stream
if {![regexp {PASS: SE reduction packets} $log]} {error "SE simulation did not pass"}
close_project
