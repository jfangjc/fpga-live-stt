set root [file normalize [file join [file dirname [info script]] ..]]
if {[llength [get_projects -quiet voice_dma]]} {
    current_project voice_dma
} else {
    open_project $root/voice_dma/voice_dma.xpr
}
set_property top voice_dma_top [current_fileset]
update_compile_order -fileset sources_1
launch_runs synth_1 -jobs 4
