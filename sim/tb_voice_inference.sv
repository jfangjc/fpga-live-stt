`timescale 1ns/1ps
module tb_voice_inference;
 reg clk=0;always #3 clk=~clk;
 reg rstn=0;reg[15:0] awaddr=0,araddr=0;reg[31:0] wdata=0;
 reg[3:0] wstrb=15;reg awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
 wire awready,wready,bvalid,arready,rvalid;wire[1:0] bresp,rresp;wire[31:0] rdata;
 wire bclk,ws,irq;
 voice_axi dut(.s_axi_aclk(clk),.s_axi_aresetn(rstn),.s_axi_awaddr(awaddr),.s_axi_awprot(3'b0),
  .s_axi_awvalid(awvalid),.s_axi_awready(awready),.s_axi_wdata(wdata),.s_axi_wstrb(wstrb),
  .s_axi_wvalid(wvalid),.s_axi_wready(wready),.s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
  .s_axi_araddr(araddr),.s_axi_arprot(3'b0),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
  .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
  .mic_bclk(bclk),.mic_ws(ws),.mic_data(1'b0),.irq(irq));
 task write_reject(input[15:0] address);
  begin
   @(negedge clk);awaddr=address;awvalid=1;
   do @(posedge clk);while(!awready);
   @(negedge clk);awvalid=0;wvalid=1;wdata=32'ha55a1234;
   do @(posedge clk);while(!wready);
   @(negedge clk);wvalid=0;
   wait(bvalid);repeat(3)begin @(negedge clk);if(!bvalid || bresp!==2'b10)$fatal(1,"Write not rejected/stable");end
   bready=1;@(posedge clk);@(negedge clk);bready=0;
  end
 endtask
 task read_check(input[15:0] address,input[1:0] response,input[31:0] value);
  begin
   @(negedge clk);araddr=address;arvalid=1;
   do @(posedge clk);while(!arready);
   @(negedge clk);arvalid=0;wait(rvalid);
   repeat(3)begin @(negedge clk);if(!rvalid || rresp!==response || rdata!==value)$fatal(1,"Read response mismatch/stall");end
   rready=1;@(posedge clk);@(negedge clk);rready=0;
  end
 endtask
 integer i;
 initial begin
  repeat(5)@(negedge clk);rstn=1;
  for(i=0;i<32;i=i+1)begin write_reject(i*4);read_check(i*4,2'b10,0);end
  write_reject(16'h7ffc);read_check(16'h7ffc,2'b10,0);
  write_reject(16'h8000);read_check(16'h8000,0,32'h10000);
  write_reject(16'h8004);read_check(16'h8004,2'b10,0);
  write_reject(16'h8008);read_check(16'h8008,0,0);
  write_reject(16'h800c);read_check(16'h800c,0,0);
  write_reject(16'h8010);read_check(16'h8010,2'b10,0);
  read_check(16'h8001,2'b10,0);
  @(negedge clk);rstn=0;repeat(3)@(negedge clk);
  if(bvalid || rvalid || irq)$fatal(1,"Response survived reset");
  $display("PASS: 77 AXI accesses, legacy MAC rejection, register reads, response backpressure and reset");$finish;
 end
 initial begin #100000;$fatal(1,"Timeout");end
endmodule
