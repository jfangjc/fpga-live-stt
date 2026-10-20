set root [file normalize [file join [file dirname [info script]] ..]]
create_project select_wrap_requant_sim $root/build/select_wrap_requant_sim -part xck26-sfvc784-2LV-c -force
add_files $root/rtl/experimental/fused_affine_quant_select_wrap.sv
add_files -fileset sim_1 $root/sim/tb_select_wrap_requant.sv
set_property top tb_select_wrap_requant [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation
run all
close_sim
set handle [open $root/build/select_wrap_requant_sim/select_wrap_requant_sim.sim/sim_1/behav/xsim/simulate.log r]
set text [read $handle];close $handle
if {![string match {*PASS: 19200 normal and wrapped float32-equivalent lanes*} $text]} {error "Exact quantizer simulation failed"}
close_project
