set root [file normalize [file join [file dirname [info script]] ..]]
open_project $root/build/adaptive_system_v2/Prototype_v3_adaptive.xpr
if {![string match {*Complete*} [get_property STATUS [get_runs synth_1]]]} {error {Chain synthesis must complete first}}
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {![string match {*Complete*} [get_property STATUS [get_runs impl_1]]]} {error {Chain implementation failed}}
open_run impl_1
report_timing_summary -file $root/reports/fused/adaptive_system_timing.rpt
report_utilization -file $root/reports/fused/adaptive_system_utilization.rpt
report_utilization -hierarchical -file $root/reports/fused/adaptive_system_hierarchical.rpt
report_drc -file $root/reports/fused/adaptive_system_drc.rpt
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set errors [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]
if {$setup<0 || $hold<0 || [llength $errors]} {error {Chain timing or DRC gate failed}}
file mkdir $root/deployment/asr-v3-adaptive
write_hw_platform -fixed -include_bit -force -file $root/deployment/asr-v3-adaptive/asr_v3_adaptive.xsa
set stream [open $root/reports/fused/adaptive_system_implementation.json w]
puts $stream "{\"clock_hz\":100000000,\"pointwise_macs\":512,\"depthwise_macs\":64,\"setup_slack_ns\":$setup,\"hold_slack_ns\":$hold,\"physical_execution\":false}"
close $stream
puts CHAIN_FIRMWARE_EXPORT_COMPLETE
