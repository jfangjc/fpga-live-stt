set root [file normalize [file join [file dirname [info script]] ..]]
set target $root/build/chain_system
if {![file exists $target/Prototype_v3_chain.xpr]} {
 open_project $root/Prototype_v2.xpr
 save_project_as -exclude_run_results -include_local_ip_cache Prototype_v3_chain $target
 close_project
}
open_project $target/Prototype_v3_chain.xpr
set old [get_files -quiet */qn_cached_axis.v]
if {[llength $old]>1} {error "Unexpected original accelerator sources"}
if {[llength $old]} {remove_files $old}
foreach path {qn_chain_axis.sv qn_chain_inner.sv qn_short_cache_core.v fused_depthwise_channel_wide.sv fused_affine_quant.v} {
 if {![llength [get_files -quiet */$path]]} {add_files $root/rtl/experimental/$path}
}
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
set bd [get_files -quiet */asr_v2_system.bd]
if {[llength $bd]!=1 || ![string match "$target/*" [file normalize $bd]]} {error "BD must belong to isolated clone"}
open_bd_design $bd
update_module_reference [get_ips {asr_v2_system_tile_0 asr_v2_system_voice_0}]
set_property -dict [list CONFIG.MAX_K {256} CONFIG.MAX_M {256}] [get_bd_cells tile]
validate_bd_design
save_bd_design
generate_target all $bd
update_compile_order -fileset sources_1
foreach run [get_runs -filter {IS_SYNTHESIS == 1}] {
 set_property STEPS.SYNTH_DESIGN.TCL.PRE $root/scripts/vivado_four_threads.tcl $run
}
set_property STEPS.OPT_DESIGN.TCL.PRE $root/scripts/vivado_four_threads.tcl [get_runs impl_1]
set cache_tile_run [get_runs -quiet asr_v2_system_tile_0_synth_1]
if {[llength $cache_tile_run]} {reset_run $cache_tile_run}
reset_run synth_1
reset_run impl_1
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {![string match "*Complete*" [get_property STATUS [get_runs synth_1]]]} {error "Fused synthesis failed"}
open_run synth_1
report_utilization -file $root/reports/fused/chain_synth_utilization.rpt
close_project
puts CHAIN_SYNTH_COMPLETE
