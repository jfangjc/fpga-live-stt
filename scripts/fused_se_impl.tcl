set root [file normalize [file join [file dirname [info script]] ..]]
set out $root/build/fused_se_impl
file mkdir $out
read_verilog $root/rtl/experimental/fused_se_reduce.v
synth_design -top fused_se_reduce -part xck26-sfvc784-2LV-c -mode out_of_context
create_clock -name se_clk -period 10.000 [get_ports aclk]
set_clock_uncertainty 0.100 [get_clocks se_clk]
set_input_delay -clock se_clk 2.000 [get_ports -filter {DIRECTION == IN && NAME != aclk && NAME != aresetn}]
set_output_delay -clock se_clk 2.000 [get_ports -filter {DIRECTION == OUT}]
set_false_path -from [get_ports aresetn]
opt_design
place_design
phys_opt_design
route_design
report_timing_summary -file $root/reports/fused/se_timing.rpt
report_utilization -file $root/reports/fused/se_utilization.rpt
report_drc -file $root/reports/fused/se_drc.rpt
write_checkpoint -force $out/fused_se_routed.dcp
set slack [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set stream [open $root/reports/fused/se_implementation.json w]
puts $stream "{\"scope\":\"standalone OOC primitive, not integrated firmware\",\"clock_hz\":100000000,\"input_output_delay_ns\":2.0,\"clock_uncertainty_ns\":0.1,\"setup_slack_ns\":$slack,\"hold_slack_ns\":$hold,\"physical_hardware_execution\":false}"
close $stream
if {$slack < 0 || $hold < 0} {error "SE primitive does not meet standalone 100 MHz timing"}
