"""Generate a replay checker for the real captured half-second DW11 channels."""
from pathlib import Path
import numpy as np
root=Path(__file__).resolve().parents[1]
directory=root/'reports/fused/depthwise_pair_vectors'
with np.load(directory/'half_second.npz') as p:
    channels,frames=p['input'].shape[1:]
    zx=int(p['xzero'])
assert channels==256 and frames==51
text='''`timescale 1ns/1ps
module tb_depthwise_model;
 reg clk=0;always #5 clk=~clk;
 reg rstn=0,cv=0,sv=0,mr=0;
 wire cr,sr,mv,ml,error,done;
 reg [87:0] weights=0;
 reg signed [31:0] bias=0,multiplier=0;
 reg [5:0] shift=1;reg[7:0] yzero=0;
 reg [127:0] sd=0;wire[127:0] md;
 reg [127:0] inputs[0:1023],outputs[0:1023];
 reg [87:0] all_weights[0:255];reg [79:0] params[0:255];
 integer cycle=0,channel=0,received=0,p;
 reg held=0,held_last;reg[127:0] held_data;
 fused_depthwise_channel #(.MAX_KERNEL(11)) dut(clk,rstn,cv,cr,13'd51,13'd51,7'd11,
  weights,bias,multiplier,shift,8'dXZERO,yzero,sd,sv,sr,md,mv,mr,ml,error,done);
 always @(negedge clk)begin cycle=cycle+1;mr=cycle%11>3;end
 always @(posedge clk)if(rstn)begin
  if(held && (!mv || md!==held_data || ml!==held_last))$fatal(1,"Stalled replay changed");
  held=mv && !mr;held_data=md;held_last=ml;
  if(mv && mr)begin
   if(md!==outputs[channel*4+received])$fatal(1,"Real vector channel=%d tile=%d",channel,received);
   if(ml!==(received==3))$fatal(1,"Replay last mismatch");
   received=received+1;
  end
 end else held=0;
 initial begin
  $readmemh("DIRECTORY/input.mem",inputs);$readmemh("DIRECTORY/output.mem",outputs);
  $readmemh("DIRECTORY/weights.mem",all_weights);$readmemh("DIRECTORY/params.mem",params);
  repeat(5)@(negedge clk);rstn=1;
  for(channel=0;channel<256;channel=channel+1)begin
   received=0;weights=all_weights[channel];bias=params[channel][31:0];
   multiplier=params[channel][63:32];shift=params[channel][69:64];yzero=params[channel][79:72];
   @(negedge clk);cv=1;do @(posedge clk);while(!cr);@(negedge clk);cv=0;
   for(p=0;p<4;p=p+1)begin
    sd=inputs[channel*4+p];sv=1;do @(posedge clk);while(!sr);@(negedge clk);sv=0;
   end
   wait(done);@(negedge clk);if(error || received!=4)$fatal(1,"Replay completion mismatch");
  end
  $display("PASS: 256 real checkpoint depthwise channels, 16384 retained bytes, masking and backpressure");$finish;
 end
 initial begin #2000000;$fatal(1,"Replay watchdog");end
endmodule
'''.replace('XZERO',str(zx)).replace('DIRECTORY',directory.as_posix())
(root/'sim/tb_depthwise_model.sv').write_text(text,encoding='utf-8')
