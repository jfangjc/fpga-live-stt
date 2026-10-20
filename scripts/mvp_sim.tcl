# Run archived regression scripts in separate projects; preserve hashed logs.
set root [file normalize [file join [file dirname [info script]] ..]]
if {[llength $argv] != 1} {error "Expected regression name"}
set name [lindex $argv 0]
if {$name ni {ab_mac_conformance branch512_ab_fast_sim branch512_ab_reset_sim branch512_ab_payload_reset_sim}} {
    error "Unknown MVP regression"
}
set file [open $root/scripts/$name.tcl r]
set source [read $file]
close $file
# Keep source resolution relative to this script; replace only project/log paths.
eval [string map [list "create_project $name " "create_project mvp_$name " \
    "build/$name/" "build/mvp_$name/" "build/$name " "build/mvp_$name " \
    "$name.sim/" "mvp_$name.sim/"] $source]
