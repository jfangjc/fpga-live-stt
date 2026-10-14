set root [file normalize [file join [file dirname [info script]] ..]]
set saved_python_env [dict create]
foreach name {PYTHONHOME PYTHONPATH} {
    if {[info exists ::env($name)]} {
        dict set saved_python_env $name $::env($name)
        unset ::env($name)
    }
}
set gate_status [catch {exec C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe $root/scripts/check_shortcache_software.py} gate_output]
dict for {name value} $saved_python_env {set ::env($name) $value}
if {$gate_status} {error $gate_output}
puts $gate_output
set simulation [open $root/reports/fused/short_cache_sim.log r]
set simulation_log [read $simulation];close $simulation
if {![regexp {PASS: 64 short-cache retained pair arithmetic} $simulation_log]} {error {RTL simulation must pass before implementation}}
open_project $root/build/short_cache_system/Prototype_v3_short_cache.xpr
if {![string match {*Complete*} [get_property STATUS [get_runs synth_1]]]} {error {Synthesis must complete first}}
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {![string match "*Complete*" [get_property STATUS [get_runs impl_1]]]} {error "Fused implementation failed"}
open_run impl_1
report_timing_summary -file $root/reports/fused/short_cache_system_timing.rpt
report_utilization -file $root/reports/fused/short_cache_system_utilization.rpt
report_drc -file $root/reports/fused/short_cache_system_drc.rpt
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set errors [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]
if {$setup<0 || $hold<0 || [llength $errors]} {error "Fused timing or DRC gate failed"}
file mkdir $root/deployment/asr-v3-shortcache
write_hw_platform -fixed -include_bit -force -file $root/deployment/asr-v3-shortcache/asr_v3_shortcache.xsa
set stream [open $root/reports/fused/short_cache_system_implementation.json w]
puts $stream "{\"clock_hz\":100000000,\"pointwise_macs\":512,\"depthwise_macs\":16,\"setup_slack_ns\":$setup,\"hold_slack_ns\":$hold,\"physical_execution\":false}"
close $stream
puts "SHORT_CACHE_FIRMWARE_EXPORT_COMPLETE"
