set root [file normalize [file join [file dirname [info script]] ..]]
create_project affine_quant_sim $root/build/affine_quant_sim -part xck26-sfvc784-2LV-c -force
add_files $root/rtl/experimental/fused_affine_quant.v
add_files -fileset sim_1 $root/sim/tb_fused_affine_quant.sv
set_property top tb_fused_affine_quant [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
set simdir $root/build/affine_quant_sim/affine_quant_sim.sim/sim_1/behav/xsim
file mkdir $simdir
foreach name {input.mem expected.mem} {file copy -force $root/sim/affine_vectors/$name $simdir/$name}
launch_simulation
run all
close_sim
set stream [open $simdir/simulate.log r];set log [read $stream];close $stream
if {![regexp {PASS: 1024 independent affine} $log]} {error "Affine primitive simulation failed"}
close_project
