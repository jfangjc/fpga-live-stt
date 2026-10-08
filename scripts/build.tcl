# Run from the Vivado Tcl Console using the saved integrated project.
set root [file normalize [file join [file dirname [info script]] ..]]
if {[llength [get_projects -quiet]] == 0} {open_project $root/Prototype.xpr}
open_bd_design [get_files voice_system.bd]
source $root/scripts/rebuild32.tcl
# Synthesis is asynchronous. Once complete, run scripts/implement.tcl.
# After bitstream generation, run scripts/export.tcl.
