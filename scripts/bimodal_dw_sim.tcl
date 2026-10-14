set root [file normalize [file join [file dirname [info script]] ..]]
create_project bimodal_dw_sim $root/build/bimodal_dw_sim -part xck26-sfvc784-2LV-c -force
add_files $root/rtl/experimental/fused_depthwise_bimodal.sv
add_files $root/rtl/experimental/fused_affine_quant_compact.sv
add_files -fileset sim_1 $root/sim/tb_bimodal_dw.sv
set_property top tb_bimodal_dw [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation
run all
close_sim
set handle [open $root/build/bimodal_dw_sim/bimodal_dw_sim.sim/sim_1/behav/xsim/simulate.log r]
set output [read $handle];close $handle
if {![string match {*PASS: 180 bimodal DW float32 cases*} $output]} {error "Adaptive depthwise regression failed"}
close_project
