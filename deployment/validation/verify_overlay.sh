#!/bin/sh
set -eu
task_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_base="$task_dir/voice-board.dtb"
task_tree="$task_dir/voice-board-merged.dtb"
task_clock=$(fdtget -t x "$task_base" /firmware/zynqmp-firmware/clock-controller phandle)
task_gic=$(fdtget -t x "$task_base" /axi/interrupt-controller@f9010000 phandle)
task_reset=$(fdtget -t x "$task_base" /firmware/zynqmp-firmware/reset-controller phandle)
[ "$(fdtget -t s "$task_tree" /fpga-region firmware-name)" = voice-prototype.bit.bin ]
[ "$(fdtget -t s "$task_tree" /voice-pl0-clock compatible)" = xlnx,fclk ]
[ "$(fdtget -t x "$task_tree" /voice-pl0-clock clocks)" = "$task_clock 47" ]
[ "$(fdtget -t u "$task_tree" /voice-pl0-clock assigned-clock-rates)" = 100000000 ]
[ "$(fdtget -t s "$task_tree" /axi/voice-afi compatible)" = xlnx,afi-fpga ]
[ "$(fdtget -t x "$task_tree" /axi/voice-afi config-afi)" = 'e a00' ]
[ "$(fdtget -t x "$task_tree" /axi/voice-afi resets)" = "$task_reset 74" ]
[ "$(fdtget -t s "$task_tree" /axi/voice@a0000000 linux,uio-name)" = voice-prototype ]
[ "$(fdtget -t x "$task_tree" /axi/voice@a0000000 reg)" = '0 a0000000 0 10000' ]
[ "$(fdtget -t x "$task_tree" /axi/voice@a0000000 interrupt-parent)" = "$task_gic" ]
[ "$(fdtget -t x "$task_tree" /axi/voice@a0000000 interrupts)" = '0 59 4' ]
echo 'PASS: merged FPGA firmware, PL0 clock, AFI/reset, UIO range and IRQ properties'
