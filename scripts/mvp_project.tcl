# Recreate an isolated MVP project from the saved BD and qualified RTL.
# Usage: -tclargs check OR build. New firmware needs fresh board qualification.
set root [file normalize [file join [file dirname [info script]] ..]]
if {[llength $argv] != 1 || [lindex $argv 0] ni {check build}} {error "Expected check or build"}
set mode [lindex $argv 0]
set target $root/build/mvp_system
if {[file exists $target]} {error "Refusing to overwrite build/mvp_system; preserve or rename it first"}
create_project kv260_asr_mvp $target -part xck26-sfvc784-2LV-c
set_property board_part xilinx.com:kv260_som:part0:2.0 [current_project]
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
foreach name {sph0645_rx.v qn_mac.v voice_dma_top.v} {add_files $root/rtl/$name}
foreach name {voice_axi_inference.v qn_branch512_ab_pw_core.v fused_affine_quant_drop_pipe.sv fused_affine_quant_select_wrap.sv fused_depthwise_droppipe.sv qn_branch512_ab_inner.sv qn_branch512_ab_axis.sv} {
    add_files $root/rtl/experimental/$name
}
add_files $root/build/generated/asr_v2_top.v
import_files -fileset sources_1 $root/build/branch512_ab166_system/Prototype_v3_branch512_ab166.srcs/sources_1/bd/asr_v2_system/asr_v2_system.bd
set bd [get_files */asr_v2_system.bd]
add_files -fileset constrs_1 $root/build/branch512_ab166_system/Prototype_v3_branch512_ab166.srcs/constrs_1/imports/Lab2b-Files/kria-constraints.xdc
add_files -fileset constrs_1 $root/hardware/mic_cdc.xdc
open_bd_design $bd
validate_bd_design
save_bd_design
generate_target all $bd
add_files [make_wrapper -files $bd -top]
set_property top asr_v2_top [get_filesets sources_1]
update_compile_order -fileset sources_1
if {[llength [get_files -quiet */sim/fast/*]]} {error "Simulation model in synthesis"}
if {$mode eq "build"} {
    foreach run [get_runs -filter {IS_SYNTHESIS == 1}] {
        set_property STEPS.SYNTH_DESIGN.TCL.PRE $root/scripts/vivado_four_threads.tcl $run
    }
    set_property STEPS.OPT_DESIGN.TCL.PRE $root/scripts/vivado_four_threads.tcl [get_runs impl_1]
    launch_runs synth_1 -jobs 1
    wait_on_run synth_1
    if {![string match {*Complete*} [get_property STATUS [get_runs synth_1]]]} {error "Synthesis failed"}
    launch_runs impl_1 -to_step write_bitstream -jobs 1
    wait_on_run impl_1
    if {![string match {*Complete*} [get_property STATUS [get_runs impl_1]]]} {error "Implementation failed"}
    open_run impl_1
    report_timing_summary -file $root/reports/mvp/rebuild_timing.rpt
    report_drc -file $root/reports/mvp/rebuild_drc.rpt
    set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
    set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
    if {$setup < 0.001 || $hold < 0 || [llength [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]]} {error "Timing/DRC gate failed"}
    file mkdir $root/deployment/mvp-rebuild
    write_hw_platform -fixed -include_bit -file $root/deployment/mvp-rebuild/kv260_asr_mvp.xsa
}
close_project
puts "PASS: MVP project $mode completed"
