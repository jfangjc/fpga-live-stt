set root [file normalize [file join [file dirname [info script]] ..]]
set python C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
exec $python -I $root/scripts/check_branch512_drop_software.py
set target $root/build/branch512_drop166_system
if {![file exists $target/Prototype_v3_branch512_drop166.xpr]} {
 open_project $root/build/branch512_outslice166_system/Prototype_v3_branch512_outslice166.xpr
 save_project_as -exclude_run_results -include_local_ip_cache Prototype_v3_branch512_drop166 $target
 close_project
}
open_project $target/Prototype_v3_branch512_drop166.xpr
foreach source {qn_branch512_outslice_axis.sv qn_branch512_slice_inner.sv fused_depthwise_bimodal.sv fused_affine_quant_compact.sv qn_stream_axis.sv qn_stream_inner.sv fused_depthwise_stream.sv qn_stream_pw_core.v fused_affine_quant_exact.sv qn_quad_axis.v qn_cached_axis.v} {
 set files [get_files -quiet */$source]
 if {[llength $files]} {remove_files $files}
}
set old_voice [get_files -quiet */voice_axi.v]
if {[llength $old_voice]} {remove_files $old_voice}
if {![llength [get_files -quiet */voice_axi_inference.v]]} {add_files $root/rtl/experimental/voice_axi_inference.v}
foreach source {qn_branch512_drop_axis.sv qn_branch512_drop_inner.sv qn_branch512_slice_pw_core.v fused_depthwise_droppipe.sv fused_affine_quant_drop_pipe.sv fused_affine_quant_select_wrap.sv} {
 if {![llength [get_files -quiet */$source]]} {add_files $root/rtl/experimental/$source}
}
if {[llength [get_files -quiet */qn_mac_model.sv]] || [llength [get_files -quiet */sim/fast/*]]} {error "Simulation MAC model must never enter synthesis"}
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
set bd [get_files -quiet */asr_v2_system.bd]
if {[llength $bd]!=1 || ![string match "$target/*" [file normalize $bd]]} {error "BD must belong to isolated clone"}
open_bd_design $bd
set processors [get_bd_cells -quiet ps]
if {[llength $processors]!=1} {error "Expected isolated processor clock provider"}
set_property CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ 166.667 $processors
update_module_reference [get_ips {asr_v2_system_tile_0 asr_v2_system_voice_0}]
set_property -dict [list CONFIG.MAX_K {256} CONFIG.MAX_M {256}] [get_bd_cells tile]
validate_bd_design
save_bd_design
generate_target all $bd
update_compile_order -fileset sources_1
foreach run [get_runs -filter {IS_SYNTHESIS == 1}] {
 set_property STEPS.SYNTH_DESIGN.TCL.PRE $root/scripts/vivado_four_threads.tcl $run
 reset_run $run
}
set_property STEPS.OPT_DESIGN.TCL.PRE $root/scripts/vivado_four_threads.tcl [get_runs impl_1]
reset_run impl_1
launch_runs synth_1 -jobs 1
wait_on_run synth_1
if {![string match "*Complete*" [get_property STATUS [get_runs synth_1]]]} {error "Branch synthesis failed"}
open_run synth_1
report_utilization -file $root/reports/fused/branch512_drop166_synth_utilization.rpt
close_project
puts BRANCH512_DROP166_SYNTH_COMPLETE
