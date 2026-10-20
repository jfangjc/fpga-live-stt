set root [file normalize [file join [file dirname [info script]] ..]]
create_project stream_sim $root/build/stream_sim -part xck26-sfvc784-2LV-c -force
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
foreach path {qn_stream_axis.sv qn_stream_inner.sv qn_stream_pw_core.v fused_depthwise_stream.sv fused_affine_quant_exact.sv} {
 add_files $root/rtl/experimental/$path
}
add_files -fileset sim_1 $root/sim/tb_qn_stream_axis.sv
set_property top tb_qn_stream_axis [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation
run all
close_sim
set handle [open $root/build/stream_sim/stream_sim.sim/sim_1/behav/xsim/simulate.log r]
set text [read $handle];close $handle
if {![string match {*PASS: 11 streamed block arithmetic*} $text]} {error "Streamed block regression failed"}
close_project
