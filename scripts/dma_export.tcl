set root [file normalize [file join [file dirname [info script]] ..]]
current_project voice_dma
if {![string match "*Complete*" [get_property STATUS [get_runs impl_1]]]} {
    error "DMA bitstream run is not complete"
}
open_run impl_1
report_timing_summary -file $root/reports/dma_timing.rpt
report_utilization -file $root/reports/dma_utilization.rpt
report_drc -file $root/reports/dma_drc.rpt
write_hw_platform -fixed -include_bit -force -file $root/voice_dma/voice_dma.xsa
