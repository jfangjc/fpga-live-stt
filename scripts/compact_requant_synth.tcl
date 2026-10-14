set root [file normalize [file join [file dirname [info script]] ..]]
set_param general.maxThreads 4
foreach variant {exact compact} {
 create_project -in_memory -part xck26-sfvc784-2LV-c
 read_verilog -sv $root/rtl/experimental/fused_affine_quant_${variant}.sv
 synth_design -top fused_affine_quant_${variant} -generic LANES=32 -mode out_of_context -part xck26-sfvc784-2LV-c
 create_clock -name aclk -period 10 [get_ports aclk]
 opt_design
 report_utilization -file $root/reports/fused/requant_${variant}_synth_utilization.rpt
 report_timing_summary -file $root/reports/fused/requant_${variant}_synth_timing.rpt
 write_checkpoint -force $root/build/requant_${variant}_synth.dcp
 close_project
}
puts REQUANT_AREA_COMPARISON_COMPLETE
