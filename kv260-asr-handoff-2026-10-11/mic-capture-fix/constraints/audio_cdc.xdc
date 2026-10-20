# audio_capture_axi timing exceptions. Replaces hardware/mic_cdc.xdc.
# Pins are unchanged (hardware/pmod.xdc): WS B10, BCLK D11, DATA E12 via voice_dma_top.
#
# Clocks: s_axi_aclk = pl_clk0 (~100 MHz); aud_clk = clk_wiz output (24.576 MHz), derived
# from pl_clk0 by an MMCM. Vivado treats the two as related, so every crossing path below
# must be excepted explicitly or it gets timed against a meaningless common period.
# After the first build, check that each get_cells/get_pins matches at least one object, and
# that report_cdc shows no unsafe crossings. [UNVERIFIED: hierarchy names until built]

# ---- Microphone pads (audio domain) -------------------------------------------------------
# DATA is sampled by a two-flop synchroniser. The RTL fixes the sampling instant at
# 162.8 ns after the BCLK rise; the SPH0645's t_DC is <= ~66 ns. Only the pad -> first flop
# path is excepted; data_sync and everything after it is timed normally.
set_false_path -from [get_ports pmod_i2s_dout] -to [get_cells -hier -filter {NAME =~ */rx/data_meta_reg}]
# BCLK and WS are registered data outputs (not clocks). Bound pad propagation.
set_max_delay -datapath_only 10.0 -from [get_cells -hier -filter {NAME =~ */rx/mic_bclk_reg}] -to [get_ports pmod_i2s_bclk]
set_max_delay -datapath_only 10.0 -from [get_cells -hier -filter {NAME =~ */rx/mic_ws_reg}] -to [get_ports pmod_i2s_lrclk]

# ---- audio -> AXI: toggle handshake ------------------------------------------------------
# Request toggle into a two-flop synchroniser.
set_false_path -to [get_cells -hier -filter {NAME =~ */req_meta_reg}]
# The payload is held for >= 62.5 us between updates; bound skew to one destination period
# so all bits are sampled from the same update.
set_max_delay -datapath_only 10.0 -from [get_cells -hier -filter {NAME =~ */pay_src_reg[*]}] -to [get_cells -hier -filter {NAME =~ */pay_cap_reg[*]}]
# Sticky FIR overlap flag (status only).
set_false_path -to [get_cells -hier -filter {NAME =~ */fir_err_meta_reg}]

# ---- AXI -> audio: quasi-static control and reset synchronisers ----------------------------
# gain_shift only changes while capture is disabled (pipeline held in reset).
set_false_path -to [get_cells -hier -filter {NAME =~ */gain_meta_reg[*]}]
# Asynchronous-assert / synchronous-deassert reset synchronisers (enable, aresetn, MMCM locked).
set_false_path -to [get_pins -hier -filter {NAME =~ */aud_glob_sync_reg[*]/CLR}]
set_false_path -to [get_pins -hier -filter {NAME =~ */aud_run_sync_reg[*]/CLR}]
