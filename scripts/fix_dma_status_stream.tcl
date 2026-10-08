set root [file normalize [file join [file dirname [info script]] ..]]
current_project voice_dma
close_design
open_bd_design [get_files voice_dma_system.bd]
set_property CONFIG.c_sg_include_stscntrl_strm 0 [get_bd_cells tensor_dma]
validate_bd_design
save_bd_design
generate_target all [get_files voice_dma_system.bd]
write_bd_tcl -force $root/scripts/voice_dma_recreate.tcl
reset_run synth_1
launch_runs synth_1 -jobs 4
puts "DMA_STATUS_STREAM_DISABLED_REBUILD_STARTED"
