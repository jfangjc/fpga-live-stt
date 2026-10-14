# Read-only critical-path diagnosis; this never exports or deploys firmware.
set root [file normalize [file join [file dirname [info script]] ..]]
set_param general.maxThreads 1
set checkpoint $root/build/branch512_outslice166_system/Prototype_v3_branch512_outslice166.runs/impl_1/asr_v2_top_routed.dcp
if {![file exists $checkpoint]} {error {Final routed checkpoint is not yet available}}
open_checkpoint $checkpoint
report_timing_summary -file $root/reports/fused/branch512_outslice166_routed_diagnosis_timing.rpt
report_timing -delay_type max -max_paths 30 -nworst 1 -input_pins -nets -file $root/reports/fused/branch512_outslice166_routed_paths.rpt
report_timing -delay_type min -max_paths 10 -nworst 1 -input_pins -nets -file $root/reports/fused/branch512_outslice166_routed_hold_paths.rpt
puts BRANCH512_OUTSLICE166_ROUTED_DIAGNOSIS_COMPLETE
