`timescale 1ns/1ps
module tb_adaptive_dw;
 reg clk=0;always #5 clk=~clk;
 reg resetn=0,cv=0,sv=0;wire cr,sr,mv,ml,err,done;
 reg [12:0] times,valid_times;reg [6:0] kernel;
 reg [1663:0] config_data;reg [511:0] data;wire [511:0] result;
 integer cycle=0,received=0,cases_done=0,offset=0;
 wire ready=cycle%11!=3 && cycle%11!=4;
 reg checking=0;
 reg [1663:0] configs[0:134];reg [63:0] metadata[0:134];
 reg [511:0] in_mem[0:209],out_mem[0:209];
 fused_depthwise_adaptive dut(.aclk(clk),.aresetn(resetn),.cfg_valid(cv),.cfg_ready(cr),
  .cfg_times(times),.cfg_valid_times(valid_times),.cfg_kernel(kernel),
  .cfg_weights(config_data[1311:0]),.cfg_bias(config_data[1439:1312]),.cfg_multiplier(config_data[1567:1440]),
  .cfg_shift(config_data[1591:1568]),.cfg_xzero(config_data[1623:1592]),.cfg_yzero(config_data[1655:1624]),
  .s_data(data),.s_valid(sv),.s_ready(sr),.m_data(result),.m_valid(mv),.m_ready(ready),.m_last(ml),.error(err),.done(done));
 always @(posedge clk)begin
  cycle<=cycle+1;
  if(resetn && checking && mv && ready)begin
   if(err || result!==out_mem[received])$fatal(1,"Adaptive DW mismatch at beat %0d",received);
   received<=received+1;
  end
  if(cycle>100000)$fatal(1,"Adaptive DW timeout");
 end
 task cfg(input integer index);begin
  @(negedge clk);config_data=configs[index];times=metadata[index][15:0];valid_times=metadata[index][31:16];kernel=metadata[index][39:32];cv=1;
  @(posedge clk);while(!cr)@(posedge clk);
  @(negedge clk);cv=0;
 end endtask
 task send(input [511:0] value);begin
  @(negedge clk);data=value;sv=1;
  @(posedge clk);while(!sr)@(posedge clk);
  @(negedge clk);sv=0;
 end endtask
 initial begin
  $readmemh("C:/Users/jfang/Documents/Vivado/Prototype_v2/verification/adaptive-dw/config.mem",configs);$readmemh("C:/Users/jfang/Documents/Vivado/Prototype_v2/verification/adaptive-dw/metadata.mem",metadata);
  $readmemh("C:/Users/jfang/Documents/Vivado/Prototype_v2/verification/adaptive-dw/input.mem",in_mem);$readmemh("C:/Users/jfang/Documents/Vivado/Prototype_v2/verification/adaptive-dw/expected.mem",out_mem);
  repeat(5)@(negedge clk);resetn=1;
  // Reset during a long-kernel four-channel MAC operation.
  cfg(44);send(in_mem[44]);repeat(10)@(negedge clk);resetn=0;
  repeat(4)@(negedge clk);resetn=1;repeat(4)@(negedge clk);
  if(mv || !cr)$fatal(1,"Adaptive DW reset did not flush transaction");
  checking=1;
  for(integer i=0;i<135;i=i+1)begin
   cfg(i);
   for(integer b=0;b<metadata[i][47:40];b=b+1)begin
    if(cycle%7==0)repeat(2)@(negedge clk);
    send(in_mem[offset+b]);
   end
   wait(done);@(negedge clk);
   offset=offset+metadata[i][47:40];
   if(received!=offset || err)$fatal(1,"Adaptive DW boundary mismatch case %0d",i);
   cases_done=cases_done+1;
  end
  checking=0;
  // Invalid parameters on a secondary channel must be rejected in short mode.
  @(negedge clk);config_data=configs[0];times=7;valid_times=7;kernel=11;
  config_data[1591:1586]=0;cv=1;@(posedge clk);@(negedge clk);cv=0;
  if(!done || !err)$fatal(1,"Secondary channel invalid shift accepted");
  $display("PASS: %0d adaptive DW float32 cases, %0d beats, 16/17 boundary, channel scales, stalls and mid-MAC reset",cases_done,received);
  $finish;
 end
endmodule
