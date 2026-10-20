# Verify installed Vivado supports the documented properties without building.
set root [file normalize [file join [file dirname [info script]] ..]]
create_project drop_incremental_api_check $root/build/drop_incremental_api_check -part xck26-sfvc784-2LV-c -force
set reference $root/build/branch512_outslice166_system/Prototype_v3_branch512_outslice166.runs/impl_1/asr_v2_top_routed.dcp
set_property AUTO_INCREMENTAL_CHECKPOINT 0 [get_runs impl_1]
set_property incremental_checkpoint.directive TimingClosure [get_runs impl_1]
add_files -fileset utils_1 -norecurse $reference
set_property incremental_checkpoint $reference [get_runs impl_1]
if {[get_property incremental_checkpoint.directive [get_runs impl_1]] ne "TimingClosure"} {error {Incremental directive was not applied}}
if {[file normalize [get_property incremental_checkpoint [get_runs impl_1]]] ne [file normalize $reference]} {error {Incremental reference differs}}
puts DROP_INCREMENTAL_API_CHECK_PASSED
close_project
