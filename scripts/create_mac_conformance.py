"""Compare the simulation MAC to the real vendor primitive with identical pins."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'rtl/experimental/qn_quad_pw_core.v').read_text()
start=text.index('   DSP48E2 #(');end=text.index('  end\n end endgenerate',start)
instance=text[start:end]
instance=instance.replace('read_valid','cem').replace('state==COMPUTE && product_valid','cep')
instance=instance.replace('!aresetn || state==CLEAR || (accept && state==HEADER)','rp').replace('!aresetn','rm')
instance=instance.replace('byte_value','av').replace('weights[o*8+7]','bv[7]').replace('weights[o*8+:8]','bv')
instance=instance.replace('.P(sum)', '.P(vendor)')
tb='''`timescale 1ns/1ps
module tb_mac_conformance;
 reg aclk=0;always #5 aclk=~aclk;
 reg [31:0] lfsr=32'hd12a0937;reg [7:0] av=0,bv=0;
 reg cem=0,cep=0,rm=1,rp=1;wire [47:0] vendor,model;
 integer cycle=0,checks=0;
'''+instance+instance.replace('DSP48E2','qn_mac_model').replace(' mac(', ' reference(').replace('.P(vendor)','.P(model)')+'''
 always @(negedge aclk)begin
  cycle=cycle+1;
  if(cycle>20)begin
   if(vendor!==model)$fatal(1,"Vendor/model mismatch cycle %0d vendor=%h model=%h",cycle,vendor,model);
   checks=checks+1;
  end
  lfsr={lfsr[30:0],lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
  av=lfsr[7:0];bv=lfsr[23:16];cem=lfsr[9];cep=lfsr[15];
  rm=cycle<20 || cycle%67==0 || cycle%109==0;
  rp=cycle<20 || cycle%83==0 || cycle%109==0;
  if(cycle==6020)begin $display("PASS: %0d vendor DSP48E2 MAC conformance cycles with independent enables and resets",checks);$finish;end
 end
endmodule
'''
(ROOT/'sim/tb_mac_conformance.sv').write_text(tb)
tcl='''set root [file normalize [file join [file dirname [info script]] ..]]
create_project mac_conformance $root/build/mac_conformance -part xck26-sfvc784-2LV-c -force
add_files $root/sim/qn_mac_model.sv
add_files -fileset sim_1 $root/sim/tb_mac_conformance.sv
set_property top tb_mac_conformance [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
launch_simulation
run all
close_sim
set f [open $root/build/mac_conformance/mac_conformance.sim/sim_1/behav/xsim/simulate.log r]
set result [read $f];close $f
if {![string match {*PASS: 6000 vendor DSP48E2 MAC conformance cycles*} $result]} {error "MAC conformance failed"}
close_project
'''
(ROOT/'scripts/mac_conformance.tcl').write_text(tcl)
print('Prepared 6000 vendor-primitive comparisons for the simulation-only MAC')
