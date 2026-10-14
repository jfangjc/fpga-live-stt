`timescale 1ns/1ps
module tb_select_wrap_requant;
 reg clk=0;always #5 clk=~clk;
 reg rstn=0,svalid=0,mready=0;
 wire sready,mvalid,error,wsready,wmvalid,werror;wire [31:0] output_data,woutput_data;
 reg [511:0] fixture[0:2399],wfixture[0:2399];integer sent=0,received=0,cycle=0,phase=0;
 reg held=0;reg [31:0] held_data,wheld_data;reg held_error,wheld_error;
 wire [511:0] row=fixture[sent<2400?sent:2399];
 fused_affine_quant_select_wrap #(.LANES(4)) dut(clk,rstn,row[127:0],row[255:128],row[383:256],row[407:384],row[439:408],
                                          svalid,sready,output_data,mvalid,mready,error,1'b0);
 fused_affine_quant_select_wrap #(.LANES(4)) wrap_dut(clk,rstn,row[127:0],row[255:128],row[383:256],row[407:384],row[439:408],svalid,wsready,woutput_data,wmvalid,mready,werror,1'b1);
 always @(negedge clk)begin
  cycle=cycle+1;mready=cycle%17>=8;
  svalid=rstn && sent<2400 && cycle%7!=1;
 end
 always @(posedge clk)begin
  if(!rstn)begin held=0;sent<=0;received<=0;end
  else begin
   if(wsready!==sready || wmvalid!==mvalid)$fatal(1,"Wrap mode handshake differs");
   if(held && (woutput_data!==wheld_data || werror!==wheld_error))$fatal(1,"Stalled wrapped output changed");
   if(held && (!mvalid || output_data!==held_data || error!==held_error))$fatal(1,"Stalled quantizer output changed");
   held=mvalid && !mready;held_data=output_data;held_error=error;wheld_data=woutput_data;wheld_error=werror;
   if(svalid && sready)sent<=sent+1;
   if(mvalid && mready)begin
    if(output_data!==fixture[received][471:440] || error!==fixture[received][472])
      $fatal(1,"Exact quantizer row %0d got %h/%b expected %h/%b",received,output_data,error,fixture[received][471:440],fixture[received][472]);
    if(woutput_data!==wfixture[received][471:440] || werror!==wfixture[received][472])$fatal(1,"Wrapped quantizer mismatch at row %0d",received);
    received<=received+1;
   end
  end
 end
 initial begin
  $readmemh("C:/Users/jfang/Documents/Vivado/Prototype_v2/verification/exact-requant/quant.mem",fixture);
  $readmemh("C:/Users/jfang/Documents/Vivado/Prototype_v2/verification/wrapped-requant/quant.mem",wfixture);
  repeat(4)@(negedge clk);rstn=1;
  wait(sent>=53);@(negedge clk);rstn=0;repeat(3)@(negedge clk);rstn=1;
  wait(received==2400);@(negedge clk);
  if(mvalid || sent!=2400)$fatal(1,"Quantizer completion mismatch");
  $display("PASS: 19200 normal and wrapped float32-equivalent lanes, invalid arithmetic, bias overflow, backpressure and pipeline reset");$finish;
 end
 initial begin #1000000;$fatal(1,"Exact quantizer watchdog");end
endmodule
