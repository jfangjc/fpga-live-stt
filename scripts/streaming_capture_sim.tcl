set root [file normalize [file join [file dirname [info script]] ..]]
create_project streaming_capture_sim $root/build/streaming-capture-sim -part xck26-sfvc784-2LV-c
add_files $root/rtl/experimental/sph0645_stream_rx.v
add_files $root/rtl/experimental/voice_axi_streaming.v
add_files -fileset sim_1 $root/sim/tb_voice_streaming.sv
set_property top tb_voice_streaming [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
launch_simulation
run all
close_sim
set f [open $root/build/streaming-capture-sim/streaming_capture_sim.sim/sim_1/behav/xsim/simulate.log r]
set result [read $f];close $f
if {![string match {*PASS: both inputs and I2S slots*} $result]} {error "Streaming capture simulation failed"}
close_project
