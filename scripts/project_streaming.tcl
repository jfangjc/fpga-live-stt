# Build a separate selectable-microphone image. Existing firmware is untouched.
set root [file normalize [file join [file dirname [info script]] ..]]
if {[llength $argv]!=1 || [lindex $argv 0] ni {check build}} {error "Expected check or build"}
set mode [lindex $argv 0]
set target $root/build/fpga-streaming
if {[file exists $target]} {error "Refusing to overwrite build/fpga-streaming"}
file mkdir $root/reports/local/streaming-hardware
create_project moonshine_stream $target -part xck26-sfvc784-2LV-c
set_param general.maxThreads 4
set_property board_part xilinx.com:kv260_som:part0:2.0 [current_project]
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
foreach name {voice_axi_streaming.v sph0645_stream_rx.v qn_bulk_axis.v fused_affine_quant.v moonshine_stream_top.v} {
 add_files $root/rtl/experimental/$name
}
import_files -fileset sources_1 $root/hardware/reference/asr_v2_system/asr_v2_system.bd
add_files -fileset constrs_1 $root/hardware/reference/kria-constraints.xdc
add_files -fileset constrs_1 $root/hardware/mic_cdc.xdc
set bd [get_files */asr_v2_system.bd]
open_bd_design $bd
update_module_reference [get_ips {asr_v2_system_tile_0 asr_v2_system_voice_0}]
set tile [get_bd_cells -hier -filter {VLNV =~ *:qn_cached_axis:*}]
if {[llength $tile]!=1} {error "Expected one bulk matrix module"}
# The portable retained-branch reference carries 256x256 limits. The raw
# Moonshine transport requires the original bulk engine's 1024x1024 cache.
set_property -dict [list CONFIG.MAX_K 1024 CONFIG.MAX_M 1024] $tile
set voice [get_bd_cells -hier -filter {VLNV =~ *:voice_axi:*}]
if {[llength $voice]!=1} {error "Expected one voice AXI module"}
set alt [create_bd_port -dir I mic_data_alt]
connect_bd_net $alt [get_bd_pins $voice/mic_data_alt]
# The bulk rollback design was qualified at 100 MHz, not the retained image's
# 166 MHz. Restore its clock constraint and reset domain in this new project.
set ps [get_bd_cells -hier -filter {VLNV =~ *:zynq_ultra_ps_e:*}]
set_property CONFIG.PSU__FPGA_PL0_ENABLE 1 $ps
set_property CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ 100 $ps
validate_bd_design
save_bd_design
generate_target all $bd
add_files [make_wrapper -files $bd -top]
set_property top moonshine_stream_top [get_filesets sources_1]
update_compile_order -fileset sources_1
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
 report_timing_summary -file $root/reports/local/streaming-hardware/timing.rpt
 report_utilization -file $root/reports/local/streaming-hardware/utilization.rpt
 report_drc -file $root/reports/local/streaming-hardware/drc.rpt
 set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
 set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
 if {$setup<0.001 || $hold<0 || [llength [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]]} {error "Timing or DRC gate failed"}
 write_hw_platform -fixed -include_bit -file $target/moonshine_stream.xsa
}
close_project
puts "PASS: streaming project $mode completed"
