set root [file normalize [file join [file dirname [info script]] ..]]
create_project mac_conformance $root/build/mac_conformance -part xck26-sfvc784-2LV-c -force
add_files $root/sim/qn_mac_model.sv
add_files -fileset sim_1 $root/sim/tb_mac_conformance.sv
set_property top tb_mac_conformance [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
launch_simulation
run all
close_sim
set f [open $root/build/mac_conformance/mac_conformance.sim/sim_1/behav/xsim/simulate.log r]
set result [read $f];close $f
if {![string match {*PASS: 6000 vendor DSP48E2 MAC conformance cycles*} $result]} {error "MAC conformance failed"}
close_project
