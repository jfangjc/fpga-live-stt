# Separate DMA integration project; the deployed Prototype project is retained.
set root [file normalize [file join [file dirname [info script]] ..]]
if {[llength [get_projects -quiet voice_cached_dma]]} {
    current_project voice_cached_dma
    close_project
}
create_project voice_cached_dma $root/voice_cached_dma -part xck26-sfvc784-2LV-c -force
set_property BOARD_PART xilinx.com:kv260_som:part0:2.0 [current_project]
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
add_files [glob $root/rtl/*.v]
# Reuse the verified PS preset and microphone interconnect in a separate BD.
set f [open $root/scripts/voice_system_recreate.tcl r]
set original [read $f]
close $f
eval [string map {"set design_name voice_system" "set design_name voice_cached_dma_system"} $original]
set_property -dict [list CONFIG.PSU__USE__S_AXI_GP2 1 CONFIG.PSU__SAXIGP2__DATA_WIDTH 128] [get_bd_cells ps]
set_property CONFIG.NUM_MI 3 [get_bd_cells axi_sc]
set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:7.1 tensor_dma]
set_property -dict [list CONFIG.c_include_sg 1 CONFIG.c_sg_include_stscntrl_strm 0 CONFIG.c_addr_width 64 \
    CONFIG.c_sg_length_width 23 CONFIG.c_m_axi_mm2s_data_width 128 \
    CONFIG.c_m_axis_mm2s_tdata_width 128 CONFIG.c_m_axi_s2mm_data_width 128 \
    CONFIG.c_s_axis_s2mm_tdata_width 128 \
    CONFIG.c_include_mm2s_dre 0 CONFIG.c_include_s2mm_dre 0] $dma
set tile [create_bd_cell -type module -reference qn_cached_axis tile]
set memory_sc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 memory_sc]
set_property -dict [list CONFIG.NUM_SI 3 CONFIG.NUM_MI 1] $memory_sc
set gpio [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 tile_control]
set_property -dict [list CONFIG.C_GPIO_WIDTH 1 CONFIG.C_ALL_OUTPUTS 1 \
    CONFIG.C_DOUT_DEFAULT 0x00000001 CONFIG.C_IS_DUAL 1 \
    CONFIG.C_GPIO2_WIDTH 2 CONFIG.C_ALL_INPUTS_2 1] $gpio
set gate [create_bd_cell -type ip -vlnv xilinx.com:ip:util_vector_logic:2.0 tile_reset_gate]
set_property -dict [list CONFIG.C_SIZE 1 CONFIG.C_OPERATION and] $gate
set status [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 tile_status]
set_property CONFIG.NUM_PORTS 2 $status
set irq [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 irq_concat]
set_property CONFIG.NUM_PORTS 3 $irq
disconnect_bd_net [get_bd_nets voice_irq] [get_bd_pins ps/pl_ps_irq0]
connect_bd_net [get_bd_pins voice/irq] [get_bd_pins irq_concat/In0]
connect_bd_net [get_bd_pins tensor_dma/mm2s_introut] [get_bd_pins irq_concat/In1]
connect_bd_net [get_bd_pins tensor_dma/s2mm_introut] [get_bd_pins irq_concat/In2]
connect_bd_net [get_bd_pins irq_concat/dout] [get_bd_pins ps/pl_ps_irq0]
connect_bd_net [get_bd_pins tile/busy] [get_bd_pins tile_status/In0]
connect_bd_net [get_bd_pins tile/error] [get_bd_pins tile_status/In1]
connect_bd_net [get_bd_pins tile_status/dout] [get_bd_pins tile_control/gpio2_io_i]
connect_bd_net [get_bd_pins tile_control/gpio_io_o] [get_bd_pins tile_reset_gate/Op1]
connect_bd_net [get_bd_pins reset/peripheral_aresetn] [get_bd_pins tile_reset_gate/Op2]
connect_bd_net [get_bd_pins tile_reset_gate/Res] [get_bd_pins tile/aresetn]
connect_bd_intf_net [get_bd_intf_pins axi_sc/M01_AXI] [get_bd_intf_pins tensor_dma/S_AXI_LITE]
connect_bd_intf_net [get_bd_intf_pins axi_sc/M02_AXI] [get_bd_intf_pins tile_control/S_AXI]
connect_bd_intf_net [get_bd_intf_pins tensor_dma/M_AXI_MM2S] [get_bd_intf_pins memory_sc/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins tensor_dma/M_AXI_S2MM] [get_bd_intf_pins memory_sc/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins tensor_dma/M_AXI_SG] [get_bd_intf_pins memory_sc/S02_AXI]
connect_bd_intf_net [get_bd_intf_pins memory_sc/M00_AXI] [get_bd_intf_pins ps/S_AXI_HP0_FPD]
connect_bd_intf_net [get_bd_intf_pins tensor_dma/M_AXIS_MM2S] [get_bd_intf_pins tile/S_AXIS]
connect_bd_intf_net [get_bd_intf_pins tile/M_AXIS] [get_bd_intf_pins tensor_dma/S_AXIS_S2MM]
set keep [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 tile_keep]
set_property -dict [list CONFIG.CONST_WIDTH 16 CONFIG.CONST_VAL 65535] $keep
connect_bd_net [get_bd_pins tile_keep/dout] [get_bd_pins tensor_dma/s_axis_s2mm_tkeep]
foreach pin {tensor_dma/s_axi_lite_aclk tensor_dma/m_axi_mm2s_aclk tensor_dma/m_axi_s2mm_aclk tensor_dma/m_axi_sg_aclk memory_sc/aclk ps/saxihp0_fpd_aclk tile/aclk tile_control/s_axi_aclk} {
    connect_bd_net [get_bd_pins ps/pl_clk0] [get_bd_pins $pin]
}
foreach pin {tensor_dma/axi_resetn memory_sc/aresetn tile_control/s_axi_aresetn} {
    connect_bd_net [get_bd_pins reset/peripheral_aresetn] [get_bd_pins $pin]
}
assign_bd_address -offset 0xA0010000 -range 0x10000 -target_address_space [get_bd_addr_spaces ps/Data] [get_bd_addr_segs tensor_dma/S_AXI_LITE/Reg] -force
assign_bd_address -offset 0xA0020000 -range 0x10000 -target_address_space [get_bd_addr_spaces ps/Data] [get_bd_addr_segs tile_control/S_AXI/Reg] -force
assign_bd_address
validate_bd_design
save_bd_design
generate_target all [get_files voice_cached_dma_system.bd]
set wrapper [make_wrapper -files [get_files voice_cached_dma_system.bd] -top]
add_files $wrapper
file mkdir $root/build/generated
set top_file [open $root/rtl/voice_dma_top.v r]
set top_source [read $top_file]
close $top_file
set cached_top [open $root/build/generated/voice_cached_dma_top.v w]
puts $cached_top [string map {voice_dma voice_cached_dma} $top_source]
close $cached_top
add_files $root/build/generated/voice_cached_dma_top.v
set_property top voice_cached_dma_top [current_fileset]
add_files -fileset constrs_1 $root/Prototype.srcs/constrs_1/imports/Lab2b-Files/kria-constraints.xdc
add_files -fileset constrs_1 $root/Prototype.srcs/constrs_1/mic_cdc.xdc
set_property USED_IN_SYNTHESIS false [get_files $root/Prototype.srcs/constrs_1/mic_cdc.xdc]
update_compile_order -fileset sources_1
write_bd_tcl -force $root/scripts/voice_cached_dma_recreate.tcl
puts "DMA_PROTOTYPE_BD_VALIDATED"

