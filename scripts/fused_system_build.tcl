set root [file normalize [file join [file dirname [info script]] ..]]
set target $root/build/fused_system
if {![file exists $target/Prototype_v3_fused_pair.xpr]} {
 open_project $root/Prototype_v2.xpr
 save_project_as -exclude_run_results -include_local_ip_cache Prototype_v3_fused_pair $target
 close_project
}
open_project $target/Prototype_v3_fused_pair.xpr
set old [get_files -quiet */qn_cached_axis.v]
if {[llength $old]>1} {error "Unexpected original accelerator sources"}
if {[llength $old]} {remove_files $old}
foreach path {qn_fused_axis.sv qn_fused_core.v fused_depthwise_channel.sv fused_affine_quant.v} {
 if {![llength [get_files -quiet */$path]]} {add_files $root/rtl/experimental/$path}
}
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
set bd [get_files -quiet */asr_v2_system.bd]
if {[llength $bd]!=1 || ![string match "$target/*" [file normalize $bd]]} {error "BD must belong to isolated clone"}
open_bd_design $bd
update_module_reference [get_ips {asr_v2_system_tile_0 asr_v2_system_voice_0}]
validate_bd_design
save_bd_design
generate_target all $bd
update_compile_order -fileset sources_1
foreach run [get_runs -filter {IS_SYNTHESIS == 1}] {
 set_property STEPS.SYNTH_DESIGN.TCL.PRE $root/scripts/vivado_four_threads.tcl $run
}
set_property STEPS.OPT_DESIGN.TCL.PRE $root/scripts/vivado_four_threads.tcl [get_runs impl_1]
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {![string match "*Complete*" [get_property STATUS [get_runs synth_1]]]} {error "Fused synthesis failed"}
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {![string match "*Complete*" [get_property STATUS [get_runs impl_1]]]} {error "Fused implementation failed"}
open_run impl_1
report_timing_summary -file $root/reports/fused/fused_system_timing.rpt
report_utilization -file $root/reports/fused/fused_system_utilization.rpt
report_drc -file $root/reports/fused/fused_system_drc.rpt
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set errors [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]
if {$setup<0 || $hold<0 || [llength $errors]} {error "Fused timing or DRC gate failed"}
file mkdir $root/deployment/asr-v3-pair
write_hw_platform -fixed -include_bit -force -file $root/deployment/asr-v3-pair/asr_v3_pair.xsa
set stream [open $root/reports/fused/fused_system_implementation.json w]
puts $stream "{\"clock_hz\":100000000,\"pointwise_macs\":512,\"depthwise_macs\":16,\"setup_slack_ns\":$setup,\"hold_slack_ns\":$hold,\"physical_execution\":false}"
close $stream
puts "FUSED_PAIR_FIRMWARE_EXPORT_COMPLETE"
