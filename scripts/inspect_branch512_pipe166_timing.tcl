# Read-only diagnosis of the saved post-placement candidate checkpoint.
set root [file normalize [file join [file dirname [info script]] ..]]
set_param general.maxThreads 1
open_checkpoint $root/build/branch512_pipe166_system/Prototype_v3_branch512_pipe166.runs/impl_1/asr_v2_top_physopt.dcp
report_timing_summary -file $root/reports/fused/branch512_pipe166_physopt_timing.rpt
report_timing -delay_type max -max_paths 30 -nworst 1 -input_pins -nets -file $root/reports/fused/branch512_pipe166_physopt_paths.rpt
report_timing -delay_type min -max_paths 10 -nworst 1 -input_pins -nets -file $root/reports/fused/branch512_pipe166_physopt_hold_paths.rpt
puts BRANCH512_PIPE166_PLACED_DIAGNOSIS_COMPLETE
