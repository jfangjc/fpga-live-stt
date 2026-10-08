set root C:/Users/jfang/Documents/Vivado/Prototype
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
update_module_reference [get_ips voice_system_voice*]
generate_target all [get_files voice_system.bd]
add_files -fileset constrs_1 $root/Prototype.srcs/constrs_1/mic_cdc.xdc
set_property USED_IN_SYNTHESIS false [get_files $root/Prototype.srcs/constrs_1/mic_cdc.xdc]
add_files -fileset sim_1 [glob $root/tb/*.v]
set_property top tb_qn_mac [get_filesets sim_1]
reset_run synth_1
foreach r [get_runs voice_system_voice*_synth_1] {reset_run $r}
launch_runs synth_1 -jobs 4


