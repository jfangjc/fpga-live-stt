# Standalone 100 MHz primitive implementation; no production project is opened.
set root [file normalize [file join [file dirname [info script]] ..]]
set out $root/build/fused_requant_impl
file mkdir $out
read_verilog $root/rtl/experimental/fused_requant.v
synth_design -top fused_requant -part xck26-sfvc784-2LV-c -mode out_of_context
create_clock -name requant_clk -period 10.000 [get_ports aclk]
set_clock_uncertainty 0.100 [get_clocks requant_clk]
set_input_delay -clock requant_clk 2.000 [get_ports -filter {DIRECTION == IN && NAME != aclk && NAME != aresetn}]
set_output_delay -clock requant_clk 2.000 [get_ports -filter {DIRECTION == OUT}]
set_false_path -from [get_ports aresetn]
opt_design
place_design
phys_opt_design
route_design
report_timing_summary -file $root/reports/fused/requant_timing.rpt
report_utilization -file $root/reports/fused/requant_utilization.rpt
report_drc -file $root/reports/fused/requant_drc.rpt
write_checkpoint -force $out/fused_requant_routed.dcp
set worst [get_timing_paths -delay_type max -max_paths 1]
set slack [get_property SLACK $worst]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set dsp [llength [get_cells -hierarchical -filter {REF_NAME =~ DSP48*}]]
set stream [open $root/reports/fused/requant_implementation.json w]
puts $stream "{\"scope\":\"standalone OOC primitive, not integrated firmware\",\"clock_hz\":100000000,\"input_output_delay_ns\":2.0,\"clock_uncertainty_ns\":0.1,\"setup_slack_ns\":$slack,\"hold_slack_ns\":$hold,\"dsp_cells\":$dsp,\"physical_hardware_execution\":false}"
close $stream
if {$slack < 0 || $hold < 0} { error "Primitive does not meet standalone 100 MHz timing" }
