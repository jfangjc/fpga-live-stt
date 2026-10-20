set root [file normalize [file join [file dirname [info script]] ..]]
create_project voice_inference_sim $root/build/voice_inference_sim -part xck26-sfvc784-2LV-c -force
add_files $root/rtl/experimental/voice_axi_inference.v
add_files $root/rtl/sph0645_rx.v
add_files -fileset sim_1 $root/sim/tb_voice_inference.sv
set_property top tb_voice_inference [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
launch_simulation
run all
close_sim
set f [open $root/build/voice_inference_sim/voice_inference_sim.sim/sim_1/behav/xsim/simulate.log r]
set result [read $f];close $f
if {![string match {*PASS: 77 AXI accesses*} $result]} {error "Inference voice slave regression failed"}
close_project
