set root [file normalize [file join [file dirname [info script]] ..]]
open_project $root/Prototype_v2.xpr
add_files $root/rtl/qn_mac.v
update_compile_order -fileset sources_1
reset_run asr_v2_system_voice_0_synth_1
reset_run synth_1
close_project
source $root/scripts/build_v2.tcl
