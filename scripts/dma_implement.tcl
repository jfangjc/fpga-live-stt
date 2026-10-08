set root [file normalize [file join [file dirname [info script]] ..]]
current_project voice_dma
if {![string match "*Complete*" [get_property STATUS [get_runs synth_1]]]} {
    error "DMA synthesis is not complete"
}
launch_runs impl_1 -to_step write_bitstream -jobs 4
