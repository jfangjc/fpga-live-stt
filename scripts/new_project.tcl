# Reproduction in a fresh checkout. Refuse to overwrite an existing project.
set root [file normalize [file join [file dirname [info script]] ..]]
if {[file exists $root/Prototype_v2.xpr]} {
    error "Project exists; use build_v2.tcl, or reproduce in a separate checkout"
}
create_project Prototype_v2 $root -part xck26-sfvc784-2LV-c
set_property BOARD_PART xilinx.com:kv260_som:part0:2.0 [current_project]
add_files -fileset constrs_1 $root/hardware/pmod.xdc
close_project
source $root/scripts/integrate_v2.tcl
