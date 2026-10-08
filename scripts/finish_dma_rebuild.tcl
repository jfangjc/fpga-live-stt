set root [file normalize [file join [file dirname [info script]] ..]]
current_project voice_dma
wait_on_run synth_1
if {![string match "*Complete*" [get_property STATUS [get_runs synth_1]]]} {
    error "DMA synthesis failed"
}
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {![string match "*Complete*" [get_property STATUS [get_runs impl_1]]]} {
    error "DMA bitstream rebuild failed"
}
source $root/scripts/dma_export.tcl
puts "DMA_STATUS_FIX_BITSTREAM_COMPLETE"
