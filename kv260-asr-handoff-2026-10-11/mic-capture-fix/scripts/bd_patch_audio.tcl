# Patch the asr_v2_system block design: swap voice_axi for audio_capture_axi and add the
# 24.576 MHz audio clock. Run inside an open project, with the BD open, after adding
# rtl/*.v and rtl/decim3_coeffs.vh to sources_1:
#   source mic-capture-fix/scripts/bd_patch_audio.tcl
# Cell and net names come from prototype-v2/scripts/asr_v2_recreate.tcl (cells ps, axi_sc,
# reset, irq_concat, voice; ports mic_bclk, mic_ws, mic_data).
# [UNVERIFIED: not yet run in Vivado. Review each step against the open BD.]

set bd [current_bd_design]

# 1. Audio clock: MMCM from pl_clk0 (99.999001 MHz preset) -> 24.576 MHz.
#    The best MMCM setting is D=1, M=10.875, O0=44.25 -> 24.576026 MHz (+1 ppm, VCO 1087.5 MHz).
#    clk_wiz chooses its own values; check CONFIG.CLKOUT1_ACTUAL_FREQ after it validates.
set aud_clk_wiz [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 aud_clk_wiz]
set_property -dict [list \
  CONFIG.PRIM_IN_FREQ {99.999001} \
  CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {24.576} \
  CONFIG.USE_RESET {false} \
  CONFIG.USE_LOCKED {true} \
  CONFIG.PRIM_SOURCE {Global_buffer} \
] $aud_clk_wiz
connect_bd_net [get_bd_pins ps/pl_clk0] [get_bd_pins aud_clk_wiz/clk_in1]

# 2. Replace the voice cell (same instance name keeps the address segment and DT node).
delete_bd_objs [get_bd_nets voice_irq] [get_bd_nets voice_mic_bclk] [get_bd_nets voice_mic_ws] \
               [get_bd_nets mic_data_1] [get_bd_intf_nets axi_sc_M00_AXI]
delete_bd_objs [get_bd_cells voice]
create_bd_cell -type module -reference audio_capture_axi voice

connect_bd_intf_net [get_bd_intf_pins axi_sc/M00_AXI] [get_bd_intf_pins voice/S_AXI]
connect_bd_net [get_bd_pins ps/pl_clk0] [get_bd_pins voice/s_axi_aclk]
connect_bd_net [get_bd_pins reset/peripheral_aresetn] [get_bd_pins voice/s_axi_aresetn]
connect_bd_net [get_bd_pins aud_clk_wiz/clk_out1] [get_bd_pins voice/aud_clk]
connect_bd_net [get_bd_pins aud_clk_wiz/locked] [get_bd_pins voice/aud_locked]
connect_bd_net [get_bd_pins voice/irq] [get_bd_pins irq_concat/In0]
connect_bd_net [get_bd_ports mic_data] [get_bd_pins voice/mic_data]
connect_bd_net [get_bd_pins voice/mic_bclk] [get_bd_ports mic_bclk]
connect_bd_net [get_bd_pins voice/mic_ws] [get_bd_ports mic_ws]

# 3. Same address window as before (64 KB at 0xA000_0000), so the DTS needs no change.
assign_bd_address -offset 0xA0000000 -range 0x00010000 \
  -target_address_space [get_bd_addr_spaces ps/Data] [get_bd_addr_segs voice/S_AXI/reg0] -force

validate_bd_design
save_bd_design
puts "audio_capture_axi integrated. Next: swap hardware/mic_cdc.xdc for constraints/audio_cdc.xdc,"
puts "rebuild, then check report_cdc, report_clock_interaction, timing and report_utilization -hierarchical."
