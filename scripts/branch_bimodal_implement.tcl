set python C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
exec $python -I [file join [file dirname [info script]] check_branch_bimodal_software.py]
set regression [open [file join [file dirname [info script]] ../build/branch_bimodal_fast_sim/branch_bimodal_fast_sim.sim/sim_1/behav/xsim/simulate.log] r]
set result [read $regression]
close $regression
if {![string match {*PASS: 25*} $result] || [regexp {Fatal:|ERROR:} $result]} {error {Full branch regression gate failed}}
set root [file normalize [file join [file dirname [info script]] ..]]
open_project $root/build/branch_bimodal_system/Prototype_v3_branch_bimodal.xpr
if {![string match {*Complete*} [get_property STATUS [get_runs synth_1]]]} {error {Chain synthesis must complete first}}
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 1
wait_on_run impl_1
if {![string match {*Complete*} [get_property STATUS [get_runs impl_1]]]} {error {Chain implementation failed}}
open_run impl_1
report_timing_summary -file $root/reports/fused/branch_bimodal_system_timing.rpt
report_utilization -file $root/reports/fused/branch_bimodal_system_utilization.rpt
report_utilization -hierarchical -file $root/reports/fused/branch_bimodal_system_hierarchical.rpt
report_drc -file $root/reports/fused/branch_bimodal_system_drc.rpt
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set errors [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]
if {$setup<0 || $hold<0 || [llength $errors]} {error {Chain timing or DRC gate failed}}
file mkdir $root/deployment/asr-v3-branch-bimodal
write_hw_platform -fixed -include_bit -force -file $root/deployment/asr-v3-branch-bimodal/asr_v3_branch_bimodal.xsa
set stream [open $root/reports/fused/branch_bimodal_system_implementation.json w]
puts $stream "{\"clock_hz\":100000000,\"pointwise_macs\":1024,\"depthwise_macs\":64,\"setup_slack_ns\":$setup,\"hold_slack_ns\":$hold,\"physical_execution\":false}"
close $stream
puts CHAIN_FIRMWARE_EXPORT_COMPLETE
