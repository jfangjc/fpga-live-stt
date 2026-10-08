create_clock -period 10.000 -name tile_clock [get_ports aclk]
set_input_delay -clock tile_clock 1.000 [get_ports {{s_axis_tdata[*]} s_axis_tvalid s_axis_tlast m_axis_tready}]
set_output_delay -clock tile_clock 1.000 [get_ports {s_axis_tready {m_axis_tdata[*]} m_axis_tvalid m_axis_tlast busy done error}]
set_false_path -from [get_ports aresetn]
