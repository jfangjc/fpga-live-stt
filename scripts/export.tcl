set root C:/Users/jfang/Documents/Vivado/Prototype
open_run impl_1
report_timing_summary -delay_type min_max -report_unconstrained -file $root/reports/timing_final.rpt
report_utilization -file $root/reports/utilization_final.rpt
report_drc -file $root/reports/drc_final.rpt
report_cdc -file $root/reports/cdc_final.rpt
write_hw_platform -fixed -include_bit -force -file $root/voice_prototype.xsa
write_bd_tcl -force $root/scripts/voice_system_recreate.tcl
