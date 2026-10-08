# Standalone synthesis keeps the working board prototype intact.
set root [file normalize [file join [file dirname [info script]] ..]]
if {[llength [get_projects -quiet tile_check]]} {
    current_project tile_check
    close_project
}
create_project tile_check $root/tile_check -part xck26-sfvc784-2LV-c -force
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
read_verilog $root/rtl/qn_tile_axis.v
synth_design -top qn_tile_axis -part xck26-sfvc784-2LV-c -mode out_of_context
create_clock -name tile_clock -period 10.0 [get_ports aclk]
set_input_delay -clock tile_clock 1.0 [get_ports {s_axis_tdata[*] s_axis_tvalid s_axis_tlast m_axis_tready}]
set_output_delay -clock tile_clock 1.0 [get_ports {s_axis_tready m_axis_tdata[*] m_axis_tvalid m_axis_tlast busy done error}]
set_false_path -from [get_ports aresetn]
opt_design
place_design
route_design
report_timing_summary -file $root/reports/tile_timing.rpt
report_utilization -file $root/reports/tile_utilization.rpt
report_drc -file $root/reports/tile_drc.rpt
write_checkpoint -force $root/tile_check/qn_tile_axis_routed.dcp
