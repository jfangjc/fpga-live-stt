# Explicit integration build. Synthesis/timing failures stop before export.
set root [file normalize [file join [file dirname [info script]] ..]]
open_project $root/Prototype_v2.xpr
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {![string match "*Complete*" [get_property STATUS [get_runs synth_1]]]} {
    error "Cached DMA synthesis failed"
}
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {![string match "*Complete*" [get_property STATUS [get_runs impl_1]]]} {
    error "Cached DMA implementation failed"
}
open_run impl_1
report_timing_summary -file $root/reports/cached_dma_timing.rpt
report_utilization -file $root/reports/cached_dma_utilization.rpt
report_drc -file $root/reports/cached_dma_drc.rpt
set drc_errors [get_drc_violations -quiet -filter {SEVERITY == Error}]
if {[llength $drc_errors]} {
    error "DRC errors remain; refusing hardware export"
}
report_clock_utilization -file $root/reports/clock_utilization.rpt
report_cdc -file $root/reports/cdc.rpt
set worst_setup [get_timing_paths -quiet -delay_type max -max_paths 1]
set worst_hold [get_timing_paths -quiet -delay_type min -max_paths 1]
if {[llength $worst_setup]==0 || [llength $worst_hold]==0} {
    error "No timing paths; refusing hardware export"
}
if {[get_property SLACK $worst_setup]<0 || [get_property SLACK $worst_hold]<0} {
    error "Cached DMA timing failed; refusing hardware export"
}
write_hw_platform -fixed -include_bit -force -file $root/deployment/asr_v2.xsa
puts "CACHED_DMA_HARDWARE_EXPORT_COMPLETE"

