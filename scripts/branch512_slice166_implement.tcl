set python C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
exec $python -I [file join [file dirname [info script]] check_branch512_slice_software.py]
set root [file normalize [file join [file dirname [info script]] ..]]
open_project $root/build/branch512_slice166_system/Prototype_v3_branch512_slice166.xpr
if {![string match {*Complete*} [get_property STATUS [get_runs synth_1]]]} {error {Chain synthesis must complete first}}
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 1
wait_on_run impl_1
if {![string match {*Complete*} [get_property STATUS [get_runs impl_1]]]} {error {Chain implementation failed}}
open_run impl_1
report_timing_summary -file $root/reports/fused/branch512_slice166_system_timing.rpt
report_utilization -file $root/reports/fused/branch512_slice166_system_utilization.rpt
report_utilization -hierarchical -file $root/reports/fused/branch512_slice166_system_hierarchical.rpt
report_drc -file $root/reports/fused/branch512_slice166_system_drc.rpt
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set errors [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]
if {$setup<0.001 || $hold<0 || [llength $errors]} {error {Chain timing or DRC gate failed}}
file mkdir $root/deployment/asr-v3-branch512-slice166
write_hw_platform -fixed -include_bit -force -file $root/deployment/asr-v3-branch512-slice166/asr_v3_branch512_slice166.xsa
set stream [open $root/reports/fused/branch512_slice166_system_implementation.json w]
puts $stream "{\"clock_hz\":166666666,\"pointwise_macs\":512,\"depthwise_macs\":64,\"setup_slack_ns\":$setup,\"hold_slack_ns\":$hold,\"physical_execution\":false}"
close $stream
puts CHAIN_FIRMWARE_EXPORT_COMPLETE
