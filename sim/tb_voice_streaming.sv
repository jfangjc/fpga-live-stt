`timescale 1ns/1ps
module tb_voice_streaming;
 reg clk=0,resetn=0;
 always #5 clk=~clk;
 reg [15:0] awaddr=0,araddr=0;
 reg [31:0] wdata=0;
 reg [3:0] wstrb=15;
 reg awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
 wire awready,wready,bvalid,arready,rvalid;
 wire [1:0] bresp,rresp;
 wire [31:0] rdata;
 wire bclk,ws,irq;
 reg data0=0,data1=0;
 voice_axi dut(.s_axi_aclk(clk),.s_axi_aresetn(resetn),
  .s_axi_awaddr(awaddr),.s_axi_awprot(3'b0),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
  .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
  .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
  .s_axi_araddr(araddr),.s_axi_arprot(3'b0),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
  .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
  .mic_bclk(bclk),.mic_ws(ws),.mic_data(data0),.mic_data_alt(data1),.irq(irq));
 reg previous_ws=1;
 integer bit_number=0;
 reg [23:0] v0,v1;
 always @(posedge clk) if(!resetn || dut.capture_reset) begin previous_ws=1;bit_number=0;end
 always @(posedge bclk) begin
  if(ws!=previous_ws)bit_number=0;else bit_number=bit_number+1;
  previous_ws=ws;
  v0=ws?24'he81280:24'h123440;
  v1=ws?24'hf34540:24'h234580;
  if(bit_number>=1 && bit_number<=24) begin
   data0<=#66 v0[24-bit_number];data1<=#66 v1[24-bit_number];
  end else begin data0<=#66 1'b1;data1<=#66 1'b1;end
 end
 task write_reg(input [15:0] address,input [31:0] value,input [3:0] strobes,input [1:0] expected);
  begin
   @(negedge clk);awaddr=address;awvalid=1;
   @(posedge clk);while(!awready)@(posedge clk);
   @(negedge clk);awvalid=0;
   repeat(3)@(negedge clk);
   wdata=value;wstrb=strobes;wvalid=1;
   @(posedge clk);while(!wready)@(posedge clk);
   @(negedge clk);wvalid=0;
   wait(bvalid);
   repeat(4)begin @(negedge clk);if(!bvalid || bresp!==expected)$fatal(1,"write response");end
   bready=1;@(negedge clk);bready=0;
  end
 endtask
 task read_reg(input [15:0] address,input [31:0] expected);
  begin
   @(negedge clk);araddr=address;arvalid=1;
   @(posedge clk);while(!arready)@(posedge clk);
   @(negedge clk);arvalid=0;
   repeat(4)begin
    if(!rvalid || rresp!==0 || rdata!==expected)$fatal(1,"read %h got %h expected %h",address,rdata,expected);
    @(negedge clk);
   end
   rready=1;@(negedge clk);rready=0;
  end
 endtask
 integer cfg;
 reg [31:0] wanted;
 initial begin
  repeat(5)@(negedge clk);resetn=1;
  read_reg(16'h8014,32'h3143494d);
  for(cfg=0;cfg<4;cfg=cfg+1)begin
   write_reg(16'h8010,cfg,15,0);
   read_reg(16'h8010,cfg);
   read_reg(16'h8000,32'h10000);
   read_reg(16'h8008,0);read_reg(16'h800c,0);
   wait(dut.captured==2);
   case(cfg)
    0:wanted=32'h00123440;1:wanted=32'hffe81280;
    2:wanted=32'h00234580;3:wanted=32'hfff34540;
   endcase
   read_reg(16'h8004,wanted);read_reg(16'h8004,wanted);
   read_reg(16'h8000,32'h10000);
  end
  write_reg(16'h8010,0,3,2);read_reg(16'h8010,3);
  write_reg(16'h8010,4,15,2);read_reg(16'h8010,3);
  write_reg(16'h8011,0,15,2);read_reg(16'h8010,3);
  write_reg(16'h0008,0,15,2);read_reg(16'h8010,3);
  $display("PASS: both inputs and I2S slots, signed FIFO samples, capture reset, AXI backpressure and invalid configuration writes");
  $finish;
 end
 initial begin #2000000;$fatal(1,"streaming capture timeout");end
endmodule
