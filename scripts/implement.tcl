set root C:/Users/jfang/Documents/Vivado/Prototype
add_files -fileset constrs_1 $root/Prototype.srcs/constrs_1/mic_cdc.xdc
set_property USED_IN_SYNTHESIS false [get_files $root/Prototype.srcs/constrs_1/mic_cdc.xdc]
add_files -fileset sim_1 [glob $root/tb/*.v]
set_property top tb_qn_mac [get_filesets sim_1]
launch_runs impl_1 -to_step write_bitstream -jobs 4
