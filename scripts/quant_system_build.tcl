# Clone sources first; no production source or run is edited.
set root [file normalize [file join [file dirname [info script]] ..]]
set target $root/build/quant_system
if {![file exists $target/Prototype_v3_quant.xpr]} {
    open_project $root/Prototype_v2.xpr
    save_project_as -exclude_run_results -include_local_ip_cache Prototype_v3_quant $target
    close_project
}
open_project $target/Prototype_v3_quant.xpr
set old [get_files -quiet */qn_cached_axis.v]
if {[llength $old]>1} {error "Unexpected raw accelerator sources"}
if {[llength $old]} {remove_files $old}
if {![llength [get_files -quiet */qn_quant_axis.v]]} {add_files $root/rtl/experimental/qn_quant_axis.v}
if {![llength [get_files -quiet */fused_affine_quant.v]]} {add_files $root/rtl/experimental/fused_affine_quant.v}
set bd [get_files -quiet */asr_v2_system.bd]
if {[llength $bd]!=1 || ![string match "$target/*" [file normalize $bd]]} {
    error "Block design must belong to the cloned project"
}
open_bd_design $bd
update_module_reference [get_ips {asr_v2_system_tile_0 asr_v2_system_voice_0}]
validate_bd_design
save_bd_design
generate_target all $bd
update_compile_order -fileset sources_1
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {![string match "*Complete*" [get_property STATUS [get_runs synth_1]]]} {error "Quantized firmware synthesis failed"}
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {![string match "*Complete*" [get_property STATUS [get_runs impl_1]]]} {error "Quantized firmware implementation failed"}
open_run impl_1
report_timing_summary -file $root/reports/fused/quant_system_timing.rpt
report_utilization -file $root/reports/fused/quant_system_utilization.rpt
report_drc -file $root/reports/fused/quant_system_drc.rpt
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set errors [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]
if {$setup<0 || $hold<0 || [llength $errors]} {error "Quantized firmware fails timing or DRC gate"}
file mkdir $root/deployment/asr-v3-quant
write_hw_platform -fixed -include_bit -force -file $root/deployment/asr-v3-quant/asr_v3_quant.xsa
set stream [open $root/reports/fused/quant_system_implementation.json w]
puts $stream "{\"scope\":\"integrated quantized-output firmware\",\"clock_hz\":100000000,\"setup_slack_ns\":$setup,\"hold_slack_ns\":$hold,\"physical_hardware_execution\":false}"
close $stream
puts "QUANTIZED_FIRMWARE_EXPORT_COMPLETE"
