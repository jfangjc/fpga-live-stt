# Separate post-route timing repair trial; this does not export or deploy firmware.
set root [file normalize [file join [file dirname [info script]] ..]]
set python C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
exec $python -I $root/scripts/check_branch512_ab_software.py
set_param general.maxThreads 4
set output $root/build/branch512_dma128166_postroute_aggressive_repair
file mkdir $output
open_checkpoint $root/reports/fused/branch512_dma128166_failed_route/asr_v2_top_routed.dcp
report_timing_summary -file $root/reports/fused/branch512_dma128166_postroute_aggressive_before.rpt
phys_opt_design -directive AggressiveExplore
report_timing_summary -file $root/reports/fused/branch512_dma128166_postroute_aggressive_timing.rpt
report_timing -delay_type max -max_paths 30 -nworst 1 -file $root/reports/fused/branch512_dma128166_postroute_aggressive_paths.rpt
report_drc -file $root/reports/fused/branch512_dma128166_postroute_aggressive_drc.rpt
report_route_status -file $root/reports/fused/branch512_dma128166_postroute_aggressive_status.rpt
write_checkpoint -force $output/asr_v2_top.dcp
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set errors [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]
set accepted [expr {$setup>=0.001 && $hold>=0 && ![llength $errors]}]
set json_bool [expr {$accepted ? "true" : "false"}]
set stream [open $root/reports/fused/branch512_dma128166_postroute_aggressive_trial.json w]
puts $stream "{\"complete\":true,\"hardware_execution\":false,\"firmware_exported\":false,\"directive\":\"AggressiveExplore\",\"setup_slack_ns\":$setup,\"hold_slack_ns\":$hold,\"error_or_critical_drc_count\":[llength $errors],\"timing_acceptance\":$json_bool}"
close $stream
puts "DMA128166_POSTROUTE_TRIAL_COMPLETE timing_acceptance=$accepted setup=$setup hold=$hold"
