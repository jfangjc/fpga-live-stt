# Synthesizes and routes the cached engine alone at the target 100 MHz.
set root [file normalize [file join [file dirname [info script]] ..]]
create_project cached_check $root/build/cached_check -part xck26-sfvc784-2LV-c -force
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
read_verilog $root/rtl/qn_cached_axis.v
synth_design -top qn_cached_axis -part xck26-sfvc784-2LV-c -mode out_of_context
create_clock -name cached_clock -period 10.0 [get_ports aclk]
set_input_delay -clock cached_clock 1.0 [get_ports {s_axis_tdata[*] s_axis_tvalid s_axis_tlast m_axis_tready}]
set_output_delay -clock cached_clock 1.0 [get_ports {s_axis_tready m_axis_tdata[*] m_axis_tvalid m_axis_tlast busy done error}]
set_false_path -from [get_ports aresetn]
opt_design
place_design
route_design
report_timing_summary -file $root/reports/cached_timing.rpt
report_utilization -file $root/reports/cached_utilization.rpt
report_drc -file $root/reports/cached_drc.rpt
write_checkpoint -force $root/build/cached_check/qn_cached_axis_routed.dcp
