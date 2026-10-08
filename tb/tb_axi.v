`timescale 1ns/1ps
module tb_axi;
    reg clk=0, resetn=0;
    always #5 clk=~clk;
    reg [15:0] awaddr=0, araddr=0;
    reg [31:0] wdata=0;
    reg [3:0] wstrb=15;
    reg awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
    wire awready,wready,bvalid,arready,rvalid;
    wire [1:0] bresp,rresp;
    wire [31:0] rdata;
    wire bclk,ws,irq;
    voice_axi dut(.s_axi_aclk(clk),.s_axi_aresetn(resetn),
      .s_axi_awaddr(awaddr),.s_axi_awprot(3'b0),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
      .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
      .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
      .s_axi_araddr(araddr),.s_axi_arprot(3'b0),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
      .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
      .mic_bclk(bclk),.mic_ws(ws),.mic_data(1'b0),.irq(irq));
    task address;
      input [15:0] a;
      begin @(negedge clk); awaddr=a; awvalid=1; @(posedge clk); while(!awready) @(posedge clk); @(negedge clk); awvalid=0; end
    endtask
    task data;
      input [31:0] d; input [3:0] st;
      begin @(negedge clk); wdata=d; wstrb=st; wvalid=1; @(posedge clk); while(!wready) @(posedge clk); @(negedge clk); wvalid=0; end
    endtask
    task response;
      input [1:0] expected;
      begin
        wait(bvalid); repeat(5) begin @(negedge clk); if(!bvalid || bresp!==expected || awready || wready) $fatal(1,"B backpressure"); end
        bready=1; @(negedge clk); bready=0;
      end
    endtask
    task read_check;
      input [15:0] a; input [31:0] d; input [1:0] response_code;
      begin
        @(negedge clk); araddr=a; arvalid=1;
        @(posedge clk); while(!arready) @(posedge clk);
        @(negedge clk); arvalid=0;
        repeat(4) begin
          if (!rvalid || rdata!==d || rresp!==response_code || arready) $fatal(1,"Read %h got %h resp%h expected %h resp%h",a,rdata,rresp,d,response_code);
          @(negedge clk);
        end
        rready=1; @(negedge clk); rready=0;
      end
    endtask
    integer i;
    initial begin
      repeat(5) @(negedge clk); resetn=1;
      // Stop serial capture to exercise queue boundaries in <1 ms.
      force dut.sample_valid=0;
      address(16'h0008); repeat(7) @(negedge clk); data(32'd19,15); response(0);
      read_check(16'h0008,19,0);
      data(32'd23,15); repeat(7) @(negedge clk); address(16'h0008); response(0);
      read_check(16'h0008,23,0);
      address(16'h0008); data(32'd31,3); response(2);
      read_check(16'h0008,23,0);
      address(16'h0009); data(32'd31,15); response(2);
      address(16'h8000); data(32'd31,15); response(2);
      read_check(16'h8004,0,2);
      read_check(16'h8001,0,2);
      read_check(16'h8010,0,2);
      @(negedge clk); force dut.sample=24'h800001; force dut.sample_valid=1;
      @(negedge clk); force dut.sample_valid=0;
      read_check(16'h8000,1,0);
      read_check(16'h8004,32'hff800001,0);
      read_check(16'h8000,32'h10000,0);
      @(negedge clk); force dut.sample=24'h123456; force dut.sample_valid=1;
      repeat(1024) @(negedge clk); force dut.sample_valid=0;
      read_check(16'h8000,32'h20400,0);
      if(!irq) $fatal(1,"IRQ threshold");
      @(negedge clk); force dut.sample_valid=1;
      repeat(3) @(negedge clk); force dut.sample_valid=0;
      read_check(16'h8000,32'h60400,0);
      read_check(16'h8008,3,0);
      read_check(16'h800c,1028,0);
      // At full, a simultaneous pop makes room for the new sample.
      @(negedge clk); force dut.sample=24'h654321; force dut.sample_valid=1; araddr=16'h8004; arvalid=1;
      @(negedge clk); arvalid=0; force dut.sample_valid=0;
      if(rdata!==32'h123456 || rresp!==0 || dut.count!==1024) $fatal(1,"Full simultaneous pop/push");
      rready=1; @(negedge clk); rready=0;
      for(i=0;i<1023;i=i+1) read_check(16'h8004,32'h123456,0);
      read_check(16'h8004,32'h654321,0);
      read_check(16'h8004,0,2);
      read_check(16'h8000,32'h50000,0);
      read_check(16'h8008,3,0);
      if(!irq) $fatal(1,"Sticky overflow IRQ");
      @(negedge clk); resetn=0; @(negedge clk); resetn=1;
      read_check(16'h8000,32'h10000,0);
      if(irq) $fatal(1,"Reset IRQ");
      $display("PASS: AXI skew/backpressure/errors; FIFO sign/overflow/full push-pop/reset");
      $finish;
    end
    initial begin #2000000; $fatal(1,"AXI timeout"); end
endmodule
