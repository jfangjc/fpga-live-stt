"""Compare old/new real DSPs and the simulation model at identical MAC latency."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def instance(name,output,vendor=True):
    core=(ROOT/('rtl/experimental/qn_branch512_slice_pw_core.v' if name=='old_mac' else 'rtl/experimental/qn_branch512_ab_pw_core.v')).read_text()
    start=core.index('   DSP48E2 #(');end=core.index('  end\n end endgenerate',start)
    text=core[start:end].replace('read_valid','cem').replace('state==COMPUTE && product_valid','cep')
    text=text.replace('!aresetn || state==CLEAR || (accept && state==HEADER)','rp').replace('!aresetn','rm')
    text=text.replace('byte_value','av').replace('weights[o*8+7]','bv[7]').replace('weights[o*8+:8]','bv')
    text=text.replace('.P(sum)',f'.P({output})').replace(' mac(',f' {name}(')
    if not vendor:text=text.replace('DSP48E2','qn_mac_ab_model')
    return text
tb='''`timescale 1ns/1ps
module tb_ab_mac_conformance;
 reg aclk=0;always #5 aclk=~aclk;
 reg [31:0] lfsr=32'hd12a0937;reg [7:0] av=0,bv=0;
 reg cem=0,cep=0,rm=1,rp=1;wire [47:0] old_value,new_value,model_value;
 integer cycle=0,checks=0,index;reg overflow_seen=0;
'''+instance('old_mac','old_value')+instance('new_mac','new_value')+instance('model_mac','model_value',False)+'''
 always @(negedge aclk)begin
  cycle=cycle+1;
  if(cycle>20)begin
   if(old_value!==new_value || new_value!==model_value)
    $fatal(1,"MAC retiming mismatch cycle %0d old=%h new=%h model=%h",cycle,old_value,new_value,model_value);
   checks=checks+1;
  end
  lfsr={lfsr[30:0],lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
  if(cycle<=20)begin rm=1;rp=1;cem=0;cep=0;av=0;bv=0;end
  else if(cycle<=65556)begin
   index=cycle-21;av=index[7:0];bv=index[15:8];cem=1;cep=1;rm=0;rp=0;
  end else if(cycle<=65558)begin cem=0;cep=1;rm=0;rp=0;end
  else if(cycle<=71558)begin
   av=lfsr[7:0];bv=lfsr[23:16];cem=lfsr[9];cep=lfsr[15];
   rm=cycle%67==0 || cycle%109==0;rp=cycle%83==0 || cycle%109==0;
  end else if(cycle<=71562)begin rm=1;rp=1;cem=0;cep=0;av=0;bv=0;end
  else begin
   av=8'h80;bv=8'h80;cem=1;cep=1;rm=0;rp=0;
   if(old_value[31] && !old_value[47])overflow_seen=1;
  end
  if(cycle==204000)begin
   if(!overflow_seen)$fatal(1,"INT32 accumulation boundary was not crossed");
   $display("PASS: %0d old/new vendor DSP and model checks, all 65536 signed byte products, independent enables/resets and INT32 overflow",checks);
   $finish;
  end
 end
endmodule
'''
dest=ROOT/'sim/tb_ab_mac_conformance.sv'
if dest.exists():assert dest.read_text()==tb
else:dest.write_text(tb,newline='\n')
tcl='''set root [file normalize [file join [file dirname [info script]] ..]]
create_project ab_mac_conformance $root/build/ab_mac_conformance -part xck26-sfvc784-2LV-c -force
add_files $root/sim/qn_mac_ab_model.sv
add_files -fileset sim_1 $root/sim/tb_ab_mac_conformance.sv
set_property top tb_ab_mac_conformance [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
launch_simulation
run all
close_sim
set f [open $root/build/ab_mac_conformance/ab_mac_conformance.sim/sim_1/behav/xsim/simulate.log r]
set result [read $f];close $f
if {![string match {*PASS: 203980 old/new vendor DSP and model checks*} $result]} {error "MAC input-register retiming failed"}
close_project
'''
dest=ROOT/'scripts/ab_mac_conformance.tcl'
if dest.exists():assert dest.read_text()==tcl
else:dest.write_text(tcl,newline='\n')
print('Prepared real old/new DSP equivalence with exhaustive byte products and independent controls')
