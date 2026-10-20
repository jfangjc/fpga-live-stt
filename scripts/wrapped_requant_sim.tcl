set root [file normalize [file join [file dirname [info script]] ..]]
create_project wrapped_requant_sim $root/build/wrapped_requant_sim -part xck26-sfvc784-2LV-c -force
add_files $root/rtl/experimental/fused_affine_quant_wrap.sv
add_files -fileset sim_1 $root/sim/tb_wrapped_requant.sv
set_property top tb_wrapped_requant [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation
run all
close_sim
set handle [open $root/build/wrapped_requant_sim/wrapped_requant_sim.sim/sim_1/behav/xsim/simulate.log r]
set text [read $handle];close $handle
if {![string match {*PASS: 9600 float32-equivalent lanes*} $text]} {error "Exact quantizer simulation failed"}
close_project
